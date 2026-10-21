import os
import importlib
import logging
import subprocess
import random
import re
import time
import socket
import requests
from datetime import datetime

from django.urls import reverse,path,include
from django.conf import settings
from django.http import HttpResponseForbidden, JsonResponse,HttpResponseServerError
from django.core.signals import request_started
from django.core.cache import cache

logger = logging.getLogger(__name__)


#WORKLOADS means the number of WORKLOADS should be started.
#If WORKLOADS is dynamic, please don't set it.
HEALTHCHECK_ENABLED = os.environ.get("HEALTHCHECK_ENABLED","true").lower() == "true"
if not HEALTHCHECK_ENABLED:
    HEALTHCHECK_ENABLED = True if cache else None

PROCESS_FILTER = os.environ.get("WORKLOAD_PROCESS_FILTER","| grep python")
CACHE_PREFIX = os.environ.get("CACHE_PREFIX","")
PORT = int(os.environ.get("WORKLOAD_PORT",8080))
WORKLOADS = int(os.environ.get("WORKLOADS",0))
WORKLOAD_DEPLOYMENT = os.environ.get("WORKLOAD_DEPLOYMENT","true").lower() == "true"
if WORKLOADS < 0 :
    WORKLOADS = 0
WORKLOAD_FAILED_THRESHOLD = int(os.environ.get("WORKLOAD_FAILED_THRESHOLD",2))


RANDOM_CHARS="abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYA0123456789~!@#$%^&*()-_+=`{}[];':\",./<>?"
RANDOM_CHARS_MAX_INDEX = len(RANDOM_CHARS) - 1

def generate_secret():
    return "".join(RANDOM_CHARS[random.randint(0,RANDOM_CHARS_MAX_INDEX)] for i in range(0,32))

secret = None

def get_workloadname(index):
    return "workload{}".format(index)

def get_local_ip():
    # Create a UDP socket
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        # Connect to a dummy external IP (doesn't have to be reachable)
        s.connect(('192.168.1.1', 1))
        ip = s.getsockname()[0]
    except Exception:
        # Fallback to localhost if network is down
        ip = '127.0.0.1'
    finally:
        s.close()
    return ip

hostname = socket.gethostname()
if WORKLOAD_DEPLOYMENT:
    registerhostname = hostname
else:
    statefulset_hostname_re = re.compile("-(?P<index>\\d+)$")
    registerhostname = get_workloadname(statefulset_hostname_re.search(hostname).group("index"))

ip = get_local_ip()

webapp_process_registerfolder = "/tmp/__webapp__/proc"

def get_processregisterfile(pid):
    return os.path.join(webapp_process_registerfolder,str(pid))


def register_webappprocess():
    """
    Register all webapp related processes 
    Healthcheck will use the processes to calculate the resources used by webapp
    """
    pid = os.getpid()
    logger.debug("Register the webapp process '{}({}).{}'.".format(hostname,ip,pid))
    try:
        if not os.path.exists(webapp_process_registerfolder):
            os.makedirs(webapp_process_registerfolder)

        registerfile = get_processregisterfile(pid)
        #register the webapp process first
        with open(registerfile,"wt") as f:
            f.write(datetime.now().strftime("%Y-%m-%dT%H:%M:%S.%f"))
    except Exception as ex:
        logger.error("Failed to register the webapp process '{}({}).{}'.".format(hostname,ip,pid))

def unregister_webappprocess():
    pid = os.getpid()
    logger.debug("Unregister the webapp process '{}({}).{}'.".format(hostname,ip,pid))
    try:
        registerfile = get_processregisterfile(pid)
        #register the webapp process first
        os.remove(registerfile)
    except Exception as ex:
        if os.path.exists(registerfile):
            logger.error("Failed to unregister the webapp process '{}({}).{}'.".format(hostname,ip,pid))


item_version = "__version__"
key_workloads = "{}__workloads__".format(CACHE_PREFIX)
key_workloads_lock = "{}lock__".format(key_workloads)

def register_webappserver(sender,environ,**kwargs):
    """
    Register a web server running in the same workload
    1. Write a server register file in workload's local file system
    2. Register the workload to a cache shared by all workloads
    """
    pid = os.getpid()
    global secret
    logger.debug("Register the webapp server '{}({}).{}'.".format(hostname,ip,pid))
    try:
        workloads_changed = False
        workloads = cache.get(key_workloads) or {item_version:0}
        if registerhostname not in workloads:
            #not registered by other webservers running in the same workload
            secret = generate_secret()
            workloads[registerhostname] = [[ip,PORT],secret,0]
            workloads_changed = True
        else:
            #already registered by other webservers, check whether the data is correct
            data = workloads[registerhostname]
            if not isinstance(data[0],list):
                data[0] = [ip,PORT]
                workloads_changed = True
            if data[0][0] != ip:
                data[0][0] = ip
                workloads_changed = True
            if data[0][1] != PORT:
                data[0][1] = PORT
                workloads_changed = True
            if data[2] != 0:
                data[2] = 0
                workloads_changed = True
            if workloads_changed:
                #workload data is changed.
                secret = generate_secret()
                data[1] = secret
            else:
                #workload data is not changed.
                secret = data[1]

        if workloads_changed:
            #save thw workloads data to cache
            save_workloads(workloads)
    
    except Exception as ex:
        logger.error("Failed to register the webapp webserver '{}({}).{}'. {}: {}".format(hostname,ip,pid,ex.__class__.__name__,str(ex)))
        #Failed to register workload, remove the server register file
        try:
            os.remove(registerfile)
        except Excepton as ex:
            if os.path.exists(registerfile):
                logger.error("Failed to remove webapp webserver register file '{}'.{}: {}".format(registerfile,ex.__class__.__name__,str(ex)))

        #ignore the exception
        return

    #register successfully, no need to register again.
    #disconnect the receiver, no need to register again.
    request_started.disconnect(dispatch_uid="register_webappserver")
    logger.debug("Successfully register the webserver({}<{}>:{}.{}) to the cache.".format(hostname,ip,PORT,pid))


#register the signal receiver to register the workload
#the signal receiver will be disconnected after successful registration
if HEALTHCHECK_ENABLED:
    #healthcheck is not initied
    request_started.connect(register_webappserver,dispatch_uid="register_webappserver")

GET_RESOURCEUSAGE_CMD = "ps ax -o %cpu=,vsz=,rss=,cmd= {}".format(PROCESS_FILTER).strip()
GET_RESOURCEUSAGE_PIPECMDS = [c.strip() for c in GET_RESOURCEUSAGE_CMD.split("|")]

def get_workload_healthcheckdata():
    #find all running web app processes
    #find the resource usage for all processes
    result = subprocess.run(GET_RESOURCEUSAGE_CMD,shell=True,capture_output=True,text=True)
    if result.returncode != 0:
        return (500,"Failed to get the resource usage data for webapp processes.{}".format(result.stderr))

    processesdata = []
    for line in result.stdout.split("\n"):
        line = line.strip()
        if not line:
            continue
        if any(c in line for c in GET_RESOURCEUSAGE_PIPECMDS):
            continue
        data = line.split(maxsplit=3)
        data[0] = float(data[0])
        data[1] = float(data[1]) / 1024
        data[2] = float(data[2]) / 1024
        del data[3]
        processesdata.append(data)

    #populate the resource data
    result = {
        "total_cpu":0,
        "total_vmemory":0,
        "total_pmemory":0,
        "processes":0,
        "min_cpu":None,
        "max_cpu":None,
        "min_vmemory":None,
        "max_vmemory":None,
        "min_pmemory":None,
        "max_pmemory":None
    }
    for data in processesdata:
        result["total_cpu"] += data[0]
        result["total_vmemory"] += data[1]
        result["total_pmemory"] += data[2]
        result["processes"] += 1

        if result["min_cpu"] is None or result["min_cpu"] > data[0]:
            result["min_cpu"] = data[0]
        if result["max_cpu"] is None or result["max_cpu"] < data[0]:
            result["max_cpu"] = data[0]

        if result["min_vmemory"] is None or result["min_vmemory"] > data[1]:
            result["min_vmemory"] = data[1]
        if result["max_vmemory"] is None or result["max_vmemory"] < data[1]:
            result["max_vmemory"] = data[1]

        if result["min_pmemory"] is None or result["min_pmemory"] > data[2]:
            result["min_pmemory"] = data[2]
        if result["max_pmemory"] is None or result["max_pmemory"] < data[2]:
            result["max_pmemory"] = data[2]

    return (200,result)

bearer_token_re = re.compile("^Bearer\\s+(?P<token>\\S+)\\s*$")
def get_auth_bearer(request):
    """
    Check the bearer authentication
    Return True if authenticated; otherwiser return False
    """
    bearer_auth = request.META.get('HTTP_AUTHORIZATION').strip() if 'HTTP_AUTHORIZATION' in request.META else ''
    m = bearer_token_re.search(bearer_auth)
    token = None
    if m:
        token = m.group('token')
    return token

key_assignedworkloads = "{}__assignedworkloads__".format(CACHE_PREFIX)
key_assignedworkloads_lock = "{}lock__".format(key_assignedworkloads)

def str_workloads(workloads):
    return ",".join(["{}={}:{}({})".format(host,data[0][0],data[0][1],data[2]) if host != item_version else "{}={}".format(host,data) for host,data in workloads.items()])


def save_workloads(workloads,unreached_servers=None):
    """
    Save the updated workloads to cache
    """
    #save the workloads
    logger.debug("Begin to save the changed workloads data({}) to cache.".format(str_workloads(workloads)))
    while True:
        if cache.add(key_workloads_lock, 1, timeout=1):
            #get the lock
            try:
                cur_workloads = cache.get(key_workloads)
                if cur_workloads and cur_workloads.get(item_version,0) != workloads[item_version]:
                    #workloads data was changed after fetching the workloads data
                    #add the new added workloads data
                    for k,v in cur_workloads.items():
                        if k == item_version:
                            continue
                        if k not in workloads and (not unreached_servers or k not in unreached_servers):
                            workloads[k] = v
                    if cur_workloads.get(item_version,0) == 0:
                        workloads[item_version] += 1
                    else:
                        workloads[item_version] = cur_workloads[item_version] + 1
                else:
                    #workloads data is not changed.
                    workloads[item_version] += 1

                #save the new workloads data
                cache.set(key_workloads,workloads)
                logger.debug("Successfully save the workloads:{}".format(str_workloads(workloads)))
                return
            finally:
                #release the lock
                cache.delete(key_workloads_lock)
        else:
            #already locked.,wait 100 milliseconds, and try again
            time.sleep(0.01)
            continue

def save_assignedworkloads(assignedworkloads):
    """
    Save the updated assigned workloads to cache
    """
    #save the workloads
    logger.debug("Begin to save the changed assigned workloads data({}) to cache.".format(assignedworkloads))
    while True:
        if cache.add(key_assignedworkloads_lock, 1, timeout=1):
            #get the lock
            try:
                cur_assignedworkloads = cache.get(key_assignedworkloads)
                if cur_assignedworkloads and cur_assignedworkloads.get(item_version,0) != assignedworkloads[item_version]:
                    #sync the latest cache data
                    for k,v in cur_assignedworkloads.items():
                        if k == item_version:
                            continue
                        if k not in assignedworkloads:
                            assignedworkloads[k] = v
                        elif v != assignedworkloads[k]:
                            assignedworkloads[k] = v

                    if cur_assignedworkloads.get(item_version,0) == 0:
                        assignedworkloads[item_version] += 1
                    else:
                        assignedworkloads[item_version] = cur_assignedworkloads[item_version] + 1
                else:
                    #workloads data is not changed.
                    assignedworkloads[item_version] += 1

                #save the new workloads data
                cache.set(key_assignedworkloads,assignedworkloads)
                logger.debug("Successfully save the assigned workloads:{}".format(assignedworkloads))
                return
            finally:
                #release the lock
                cache.delete(key_assignedworkloads_lock)
        else:
            #already locked.,wait 100 milliseconds, and try again
            time.sleep(0.01)
            continue

def populate_summary_data(datas):
    """
    Populate the resource summary data from workloads' resource usage data
    """
    summary = {
        "total_cpu":0,
        "total_vmemory":0,
        "total_pmemory":0,
        "total_processes":0,
        "running_workloads":0,
        "failed_workloads":0,
        "min_process_cpu":None,
        "max_process_cpu":None,
        "min_process_vmemory":None,
        "max_process_vmemory":None,
        "min_process_pmemory":None,
        "max_process_pmemory":None
    }
    for servername,serverdata in datas.items():
        if isinstance(serverdata,str):
            summary["failed_workloads"] += 1
            continue
        summary["running_workloads"] += 1
        summary["total_cpu"] += serverdata["total_cpu"]
        summary["total_vmemory"] += serverdata["total_vmemory"]
        summary["total_pmemory"] += serverdata["total_pmemory"]
        summary["total_processes"] += serverdata["processes"]

        if summary["min_process_cpu"] is None or summary["min_process_cpu"] > serverdata["min_cpu"]:
            summary["min_process_cpu"] = serverdata["min_cpu"]
        if summary["max_process_cpu"] is None or summary["max_process_cpu"] < serverdata["max_cpu"]:
            summary["max_process_cpu"] = serverdata["max_cpu"]

        if summary["min_process_vmemory"] is None or summary["min_process_vmemory"] > serverdata["min_vmemory"]:
            summary["min_process_vmemory"] = serverdata["min_vmemory"]
        if summary["max_process_vmemory"] is None or summary["max_process_vmemory"] < serverdata["max_vmemory"]:
            summary["max_process_vmemory"] = serverdata["max_vmemory"]

        if summary["min_process_pmemory"] is None or summary["min_process_pmemory"] > serverdata["min_pmemory"]:
            summary["min_process_pmemory"] = serverdata["min_pmemory"]
        if summary["max_process_pmemory"] is None or summary["max_process_pmemory"] < serverdata["max_pmemory"]:
            summary["max_process_pmemory"] = serverdata["max_pmemory"]

    datas["summary"] = summary

workload_healthcheck_url = None
headers={"Authorization":None,"Accept": "application/json"}

def harvest_healthdata(request):
    global secret

    global workload_healthcheck_url
    if not workload_healthcheck_url:
        workload_healthcheck_url = reverse('healthcheck:workload_healthdata')

    workloads = cache.get(key_workloads) or {item_version:0}
    workloads_changed = False
    logger.debug("Get the workloads from cache :{}".format(str_workloads(workloads)))

    if registerhostname not in workloads:
        secret = generate_secret()
        workloads[registerhostname] = [[ip,PORT],secret,0]
        workloads_changed = True

    servers_res = {}
    unreached_servers = []
    #havest health data from all workloads
    for servername, serverdata in workloads.items():
        if servername == item_version:
            continue
        if servername == registerhostname:
            servers_res[servername] = get_workload_healthcheckdata()
            continue

        serverip,port = serverdata[0]
        headers["Authorization"] = "Bearer {}".format(serverdata[1])
        headers["host"] = request.get_host()
        url = "http://{}:{}{}".format(serverip,port,workload_healthcheck_url)
        try:
            res = requests.get(url,headers=headers)
        except Exception as ex:
            #the server is offline, don't add the data to servers_res
            workloads_changed = True
            serverdata[2] += 1
            if serverdata[2] >= WORKLOAD_FAILED_THRESHOLD:
                #continuous failed times is greater than WORKLOAD_FAILED_THRESHOLD.
                unreached_servers.append(servername)
            servers_res[servername] = (-1,"{1}:{2},url={0}".format(url,ex.__class__.__name__,str(ex)))
            continue
        if res.status_code in (502,503,504):
            #the server is offline, don't add the data to servers_res
            workloads_changed = True
            serverdata[2] += 1
            if serverdata[2] >= WORKLOAD_FAILED_THRESHOLD:
                #continuous failed times is greater than WORKLOAD_FAILED_THRESHOLD.
                unreached_servers.append(servername)
            servers_res[servername] = (res.status_code,"{1}:{2},url={0}".format(url,res.status_code,res.text))
        elif res.status_code == 200:
            #the server is in good health, add the health data to servers_res
            servers_res[servername] = (200,res.json())
            if serverdata[2] > 0:
                serverdata[2] -= 1
                workloads_changed = True
        else:
            #the server is online, but running into error, add the error message to servers_res
            servers_res[servername] = (res.status_code,"{1}: {2}. url={0}".format(res.status_code,res.text,url))
            if serverdata[2] > 0:
                serverdata[2] -= 1
                workloads_changed = True

    for servername in unreached_servers:
        del workloads[servername]

    logger.debug("healthdata harvest result :{}".format(servers_res))

    if workloads_changed:
        save_workloads(workloads,unreached_servers)

    return (workloads,servers_res)

OFFLINE_STATUSCODE_LIST = (502,503,504,-1,-2)
if WORKLOADS > 0 and WORKLOAD_DEPLOYMENT:
    #has a fixed number of workloads and it is a deployment
    WORKLOADNAMES = [get_workloadname(index) for index in range(WORKLOADS)]
    def healthdata_view(request):
        #process the workloads which are alreasy assigned a workload name
        workloads,servers_res = harvest_healthdata(request)
        assignedworkloads = cache.get(key_assignedworkloads) or {item_version:1}
        logger.debug("Get assigned workloads:{}".format(assignedworkloads))
        datas = {}
        index = 0
        reassigned_workloads = 0
        for workloadname in WORKLOADNAMES:
            servername = assignedworkloads.get(workloadname)
            if not servername:
                #workloadname is not assined to a server
                reassigned_workloads += 1
                continue

            #workload name is assigned to a server
            if servername not in servers_res :
                #the server is not available
                reassigned_workloads += 1
                continue

            datas[servername] = servers_res[servername]
            if servers_res[servername][0] in OFFLINE_STATUSCODE_LIST:
                #Related workload is offline, need to reassign another workload
                reassigned_workloads += 1
            del servers_res[servername]

        assignedworkloads_changed = False
        if reassigned_workloads > 0:
            #Some workloads are not assigned a workload name or are not available
            #Using the following to replace the exisint one with new one if possible
            #Step 1: Replace the unavailable server with a new one 
            #Step 2: Assign the new server to the missing assignedworkloads(missed in the assignedworkloads before)
            step = 0
            while reassigned_workloads > 0:
                step += 1
                for workloadname in WORKLOADNAMES:
                    servername = assignedworkloads.get(workloadname)
                    if servername in datas and datas[servername][0] not in OFFLINE_STATUSCODE_LIST:
                        #related server is online.no need to reassign
                        continue
                    elif step == 1:
                        #step 1 only reassign the assigned workloads
                        if workloadname not in assignedworkloads:
                            continue
                    replacedservername = None
                    for name,res in servers_res.items():
                        if res[0] == 200:
                            #found a good one, choose it
                            replacedservername = name
                            break
                        elif res[0] in OFFLINE_STATUSCODE_LIST:
                            continue
                        elif not replacedservername:
                            #fond a available one, but has some issues,choose it if can't find a good one
                            replacedservername = name

                    logger.debug("Replaced {1} with {2} for workload({0})".format(workloadname,servername,replacedservername))
                    if replacedservername:
                        datas[replacedservername] = servers_res[replacedservername]
                        del servers_res[replacedservername]
                        assignedworkloads[workloadname] = replacedservername
                        assignedworkloads_changed = True

                    if servers_res:
                        reassigned_workloads -= 1
                    else:
                        reassigned_workloads = 0
                    if reassigned_workloads == 0:
                        break

            if assignedworkloads_changed:
                #save the workloads
                logger.debug("Save the changed running workloads data({}).".format(assignedworkloads))
                save_assignedworkloads(assignedworkloads)

        #map the healthdata result to workload. and remove status code
        result = {}
        for workloadname in WORKLOADNAMES:
            servername = assignedworkloads.get(workloadname)
            if not servername:
                result[workloadname] = "Can't find an available host for this non-assigned host.registered workloads: {0}, assigned workloads:{1}".format(str_workloads(workloads),assignedworkloads)
            elif servername not in datas:
                result[workloadname] = "Can't find an available host for this assigned offline host({2}).registered workloads: {0}, assigned workloads:{1}".format(str_workloads(workloads),assignedworkloads,servername)
            else:
                result[workloadname] = datas[servername][1]
                result[workloadname]["hostname"] = servername

        datas.clear()

        populate_summary_data(result)

        return JsonResponse(result)

elif WORKLOADS > 0 and not WORKLOAD_DEPLOYMENT:
    WORKLOADNAMES = [get_workloadname(index) for index in range(1,WORKLOADS + 1,1)]
    def healthdata_view(request):
        workloads,servers_res = harvest_healthdata(request)

        result = {}
        for servername in WORKLOADNAMES:
            if result in servers_res:
                result[servername] = servers_res[servername][1]
            else:
                result[servername] = "Workload is offline.workloads={}".format(str_workloads(workloads))

        populate_summary_data(result)

        return JsonResponse(result)
else:
    def healthdata_view(request):
        workloads,servers_res = harvest_healthdata(request)

        result = {}
        for servername, serverdata in servers_res.items():
            result[servername] = serverdata[1]

        populate_summary_data(result)

        return JsonResponse(result)

def workload_healthdata_view(request):
    global secret
    token = get_auth_bearer(request)
    if not token:
        return HttpResponseForbidden("Missing access token")

    if not secret or secret != token:
        workloads = cache.get(key_workloads)
        data = workloads.get(registerhostname)
        if data:
            secret = data[1]
        
        if secret != token:
            return HttpResponseForbidden("Access token doesn't match")

    statuscode,data = get_workload_healthcheckdata()
    if statuscode == 200:
        return JsonResponse(data)
    else:
        return HttpResponseServerError(data)

def register_healtcheckurls():
    #Add urls
    rootconf_module = importlib.import_module(settings.ROOT_URLCONF)
    if not rootconf_module:
        raise Exception("Failed to load module '{}'".format(settings.ROOT_URLCONF))
    
    if HEALTHCHECK_ENABLED:
        urlpatterns = [
                path('healthcheck/healthdata', healthdata_view,name="healthdata"),
                path('workload/healthcheck/healthdata',workload_healthdata_view,name="workload_healthdata")
        ]
    else:
        urlpatterns = []

    rootconf_module.urlpatterns.append(path('',include((urlpatterns,'healthcheck'),namespace="healthcheck")))

