# Supercast plugin for supervisor
# place this file somewhere on the python path
# add something like this to the supervisor.conf (only the first 3 lines are required)
# You will have to change this to fit the specific environment

#  [rpcinterface:supercast]
#  supervisor.rpcinterface_factory = supercast.make_supercast
#  urls=ws://frontend1.company.com:12345/supervisor-updates,ws://frontend1.company.com:12345/supervisor-updates
#  environment=Production
#  subEnv=SpecialOps
#  clusterId=cluster1
#  returnProxy=proxy1.company.com:8080
#  logfile=supercast.log
#


import time
import pwd
import os
import threading
import platform
import traceback
import socket
import websocket
import logging
import random
import json
import re
from logging.handlers import RotatingFileHandler
from supervisor import events, states, rpcinterface
from supervisor.states import ProcessStates
from supervisor.options import VERSION
from supervisor.datatypes import signal_number
from supervisor.xmlrpc import (
    Faults,
    RPCError,
)


class tryTo:
    def __init__(self, f, logger):
        self.f = f
        self.logger = logger

    def __call__(self, *args, **kwargs):
        try:
            s = time.time()
            self.f(*args, **kwargs)
            self.logger.debug("Called " + self.f.__name__ + " in " + str(round((time.time() - s) * 1000)) + "ms")
        except:
            self.logger.critical(traceback.format_exc())


class Supervisor:
    """Represents a supervisor process instance"""
    def __init__(self, supervisorid=None, host=None, rpcport=-1, env=None, subEnv="", dockerId="", clusterId="", returnProxy="", state=None, pid=0,
                 configerror = None, configadded = [], configupdated = [], configremoved = [], since=None, motd=""):
        # Note: changing member variable names will change the json object property names used in the server messages
        self.supervisorid = supervisorid
        self.host = host
        self.rpcport = rpcport
        self.env = env
        self.subEnv = subEnv
        self.supervisorversion = VERSION
        self.os = platform.platform()
        self.osversion = platform.version()
        self.arch = platform.machine()
        self.processor = platform.processor()
        self.dockerId = dockerId
        self.clusterId = clusterId
        self.returnProxy = returnProxy
        self.state = state
        self.statename = states.getSupervisorStateDescription(state)
        self.supervisorpid = pid
        self.since = since or time.time() * 1000
        self.configerror = configerror
        self.configadded = configadded
        self.configupdated = configupdated
        self.configremoved = configremoved
        self.motd = motd
        self.updateTime = time.time() * 1000



    def __str__(self):
        return "Supervisor{supervisorid=" + self.supervisorid + \
               ", host=" + self.host + \
               ", rpcport=" + str(self.rpcport) + \
               ", env=" + self.env + \
               ", subEnv=" + self.subEnv + \
               ", supervisorversion=" + self.supervisorversion + \
               ", os=" + self.os + \
               ", osverson=" + self.osversion + \
               ", arch=" + self.arch + \
               ", dockerId=" + self.dockerId + \
               ", clusterId=" + self.clusterId + \
               ", dockerId=" + self.dockerId + \
               ", returnProxy=" + self.returnProxy + \
               ", processor=" + self.processor + \
               ", state=" + str(self.state) + \
               ", statename=" + self.statename + \
               ", supervisorpid=" + str(self.supervisorpid) + \
               ", since=" + str(self.since) + \
               ", configerror=" + self.configerror + \
               ", configadded=" + str(self.configadded) if self.configadded else "" + \
               ", configupdated=" + str(self.configupdated) if self.configupdated else "" + \
               ", configremoved=" + str(self.configremoved) if self.configremoved else "" + \
               "}"


class Process:
    """Represents a process running under supervisor"""

    def __init__(self, supervisorid=None, host=None, env=None, subEnv=None, process=None, state=None, pid=None):
        # Note: changing member variable names will change the json object property names used in the server messages
        self.supervisorid = supervisorid
        self.host = host
        self.env = env
        self.subEnv = subEnv
        self.since = time.time() * 1000
        self.updateTime = time.time() * 1000

        if process is not None:
            pconfig = process.config
            gconfig = process.group.config

            self.group = gconfig.name
            self.name = pconfig.name
            self.pid = pid or process.pid
            self.childpids = ""
            self.start = process.laststart * 1000
            self.stop = process.laststop * 1000
            self.state = state if state is not None else process.get_state()
            self.since = max(process.laststart, process.laststop) * 1000
            self.statename = states.getProcessStateDescription(self.state)
            self.spawnerr = process.spawnerr or ''
            self.exitstatus = process.exitstatus or 0
            self.command = pconfig.command
            self.uid = pconfig.uid or os.getuid()
            self.username = self.resolveUsername(self.uid)
            self.directory = pconfig.directory
            self.autostart = pconfig.autostart
            self.startsecs = pconfig.startsecs
            self.startretries = pconfig.startretries
            self.stopsignal = pconfig.stopsignal
            self.stopwaitsecs = pconfig.stopwaitsecs
            self.exitcodes = str(pconfig.exitcodes)
            self.stdout_logfile = pconfig.stdout_logfile
            self.stderr_logfile = pconfig.stderr_logfile
            self.environmentVars = pconfig.environment

    def resolveUsername(self, id):
        if id is not None:
            try:
                uid = int(id)
                if uid > 0:
                    return pwd.getpwuid(uid)[0]
            except ValueError:
                pass
        return ""


    def __str__(self):
        return "Process{group=" + self.group + \
               ", name=" + self.name + \
               ", supervisorid=" + self.supervisorid + \
               ", host=" + self.host + \
               ", env=" + self.env + \
               ", subEnv=" + self.subEnv + \
               ", state=" + str(self.state) + \
               ", statename=" + self.statename + \
               ", since=" + str(self.since) + \
               "}"


class Connection:
    def __init__(self, url, logger):
        self.logger = logger
        # flag to signal refresh needed - so it can be done in the supervisor thread
        self.needs_refresh = False
        self.connected = False
        self.died = False
        self.url = url
        self.ws = websocket.WebSocketApp(url, on_open=self.on_open, on_close=self.on_close, on_error=self.on_error)

    def start(self):
        # background websocket thread
        self.logger.warn("Opening connection to " + self.url)
        wst = threading.Thread(target=self.connect)
        wst.daemon = True
        wst.start()

    def on_open(self, ws):
        self.logger.warn("Connection opened")
        self.connected = True
        self.needs_refresh = True

    def on_close(self, ws):
        self.logger.warn("Connection closed")
        self.died = True

    def on_error(self, ws, e):
        self.logger.warn("Websocket error: " + str(e))
        self.died = True

    def connect(self):
        try:
            # usual socket timeout 5 mins so send ping every 150s
            self.ws.run_forever(ping_interval=150)
        except:
            self.logger.warn(traceback.format_exc())
        self.died = True

    def shutdown(self):
        if self.died:
            return
        self.logger.warn("Closing connection")
        try:
            self.ws.close()
        except:
            self.logger.warn(traceback.format_exc())

    def updateProcess(self, p):
        if self.died:
            return
        self.logger.debug("Updating process: %s ", str(p))
        try:
            self.ws.send(json.dumps({"process": p.__dict__}))
        except:
            self.logger.warn(traceback.format_exc())

    def deleteGroup(self, name):
        if self.died:
            return
        self.logger.info("deleting group: %s", name)
        try:
            self.ws.send(json.dumps({"deleteGroup": name}))
        except:
            self.logger.warn(traceback.format_exc())

    def updateSupervisor(self, s):
        if self.died:
            return
        self.logger.debug("Updating supervisor: %s ", str(s))
        try:
            self.logger.info(s.__dict__)
            self.ws.send(json.dumps({"supervisor": s.__dict__}))
        except:
            self.logger.warn(traceback.format_exc())
        self.needs_refresh = False

    def fullUpdateComplete(self):
        try:
            self.ws.send(json.dumps({"updateComplete": True}))
        except:
            self.logger.warn(traceback.format_exc())



EVENTS_TO_STATES = {
    events.ProcessStateExitedEvent: ProcessStates.EXITED,
    events.ProcessStateFatalEvent: ProcessStates.FATAL,
    events.ProcessStateRunningEvent: ProcessStates.RUNNING,
    events.ProcessStateStartingEvent: ProcessStates.STARTING,
    events.ProcessStateStoppedEvent: ProcessStates.STOPPED,
    events.ProcessStateBackoffEvent: ProcessStates.BACKOFF,
    events.ProcessStateStoppingEvent: ProcessStates.STOPPING,
    events.ProcessStateUnknownEvent: ProcessStates.UNKNOWN
}


class Supercast:
    """Publishes supervisor state changes via websockets."""

    def __init__(self, supervisord, host, environment, subEnv, urls, urlIndex, clusterId, returnProxy, logger):
        self.supervisord = supervisord
        self.host = host
        self.env = environment
        self.subEnv = subEnv
        self.urls = urls
        self.urlIndex = urlIndex
        self.clusterId = clusterId
        self.returnProxy = returnProxy
        self.logger = logger
        self.supervisorid = supervisord.options.identifier
        self.connection = None
        self.configerror = None
        self.configadded = []
        self.configupdated = []
        self.configremoved = []
        self.since = None
        self.repubSecs = 59 * 60  # every 1 hours
        self.lastRepub = 0
        self.closed = False
        # cope with order of group delete and update
        self.deletedGroups = set()

        if self.supervisorid == "supervisor":
            raise Exception("You must set the identifier in the supervisor config to something unique")

        self.cgroupPattern = re.compile(r"docker[-/]([0-9a-f]+)")

        # subscribe to what we're interested in
        events.subscribe(events.SupervisorStateChangeEvent, tryTo(self.onSupervisorStateChange, logger))
        events.subscribe(events.ProcessStateEvent, tryTo(self.onProcessStateChange, logger))
        events.subscribe(events.ProcessGroupAddedEvent, tryTo(self.onGroupAdd, logger))
        events.subscribe(events.ProcessGroupRemovedEvent, tryTo(self.onGroupRemove, logger))
        events.subscribe(events.Tick5Event, tryTo(self.onTick, logger))

    def onSupervisorStateChange(self, event):
        if self.closed:
            return
        self.logger.info("Supercast got supervisord state change " + str(event))
        if isinstance(event, events.SupervisorRunningEvent):
            # finished started and forked already so create the connection now
            # (Any threads created before now die when the process forks)
            self.makeNewconnection()
        self.since = time.time() * 1000
        self.updateSupervisorState()
        # Re shutdown: unfortunately we get the supervisor shutdown event before the process shutdowns,
        # so we cant disconnect at this point.

    def onProcessStateChange(self, event):
        if self.closed or not self.connection.connected:
            return
        self.logger.info("Supercast Received process state event " + event.__class__.__name__ + " " + str(event))
        self.updateProcess(event.process, self.eventToState(event), self.eventToPid(event))


    def onGroupRemove(self, event):
        # This can come before the process stopped event (due to the way the stopped event is sent)
        # need to rework this
        # poss block further updates for removed groups
        if self.closed:
            return
        self.logger.info("Received group remove event " + str(event).strip())
        # remember group is deleted in case process update follows this
        self.deletedGroups.add(event.group)
        self.connection.deleteGroup(event.group)

    def onGroupAdd(self, event):
        # this can come before the previous process stopped event (due to the way the stopped event is sent)
        # need to rework this
        if self.closed:
            return
        self.logger.info("Supercast Received group add event " + str(event).strip())
        group = self.supervisord.process_groups.get(event.group)
        # undelete group
        self.logger.warn("group add " + event.group)
        self.deletedGroups.remove(event.group)

        processes = list(group.processes.values())
        for process in processes:
            self.updateProcess(process, None, None)

    def onTick(self, e):
        if self.closed:
            return
        # re-create the connection if it died
        if self.connection is not None:
            if self.connection.died:
                self.makeNewconnection()

            # check for config changes
            # really should check file timestamps as this is quite expensive - but this will do for now
            changed = self.checkForConfigChanges()
            if changed:
                self.logger.info("Config change status updated")
                self.since = time.time() * 1000
                self.republish_all()

            # republish everything regularly or the servers will expire us
            if self.lastRepub <= time.time() - self.repubSecs:
                self.republish_all()

            if self.connection.needs_refresh:
                self.republish_all()


    def checkForConfigChanges(self):
        try:
            self.supervisord.options.process_config(do_usage=False)
        except ValueError as e:
            msg = str(e.message)
            if self.configerror != msg:
                self.configerror = msg
                self.configadded, self.configupdated, self.configremoved = [], [], []
                return True
            return False
        diffs = [[g.name for g in x] for x in self.supervisord.diff_to_active()]
        if diffs != [self.configadded, self.configupdated, self.configremoved]:
            self.configadded, self.configupdated, self.configremoved = diffs
            self.configerror = None
            return True
        if self.configerror is not None:
            self.configerror = None
            return True
        return False

    def makeNewconnection(self):
        if self.closed:
            return
        self.logger.info("Creating new connection...")
        connection = Connection(self.urls[self.urlIndex], self.logger)
        self.urlIndex = (self.urlIndex + 1) % len(self.urls)
        connection.start()
        self.connection = connection
        if self.closed:
            connection.shutdown()

    def republish_all(self):
        if not self.connection.connected:
            return
        self.lastRepub = time.time()
        self.logger.info("Publishing full refresh.")

        # replace the data for this supervisor instance
        # initial supervisor message must come before processes
        self.updateSupervisorState()

        # update the processes
        self.updateAllProcesses()

        # tell the server we've sent everything (and can therefore cleanup anything from previous connection)
        self.connection.fullUpdateComplete()

    def updateAllProcesses(self):
        if not self.connection.connected:
            return
        self.logger.info("Updating all processes")
        groups = list(self.supervisord.process_groups.values())
        for group in groups:
            processes = list(group.processes.values())
            for process in processes:
                self.updateProcess(process, None, None)

    def updateProcess(self, process, state, pid):
        if not self.connection.connected:
            return
        if process.group.config.name in self.deletedGroups:
            self.logger.warn("Not updating process %s in deleted group %s" % (process.config.name, process.group.config.name))
            return
        newstate = state if state is not None else process.get_state()
        newpid = pid or process.pid

        self.logger.info(
            "Updating process %s %s %s" % (process.config.name, states.getProcessStateDescription(newstate), newpid))

        p = Process(self.supervisorid, self.host, self.env, self.subEnv, process, newstate, newpid)
        self.connection.updateProcess(p)

    def updateSupervisorState(self):
        if not self.connection.connected:
            return
        self.logger.info("Updating Supervisor info %s %s %s %s %s", self.host, self.supervisorid, self.env, self.subEnv, states.getSupervisorStateDescription(self.supervisord.options.mood))
        port = self.getHttpPort()
        mood = self.supervisord.options.mood
        if mood == states.SupervisorStates.RESTARTING:
            mood = states.SupervisorStates.SHUTDOWN
        s = Supervisor(self.supervisorid, self.host, port, self.env, self.subEnv, self.getDockerId(), self.clusterId, self.returnProxy, mood, self.supervisord.options.get_pid(), self.configerror, self.configadded, self.configupdated, self.configremoved, self.since, self.getMotd())
        self.connection.updateSupervisor(s)

    def getHttpPort(self):
        cfgs = self.supervisord.options.server_configs
        for c in cfgs:
            if c['section'] == "inet_http_server":
                return c['port']
        return 0

    def getMotd(self):
        motd = ""
        try:
            f = open("/etc/motd")
            motd = f.read()
            f.close()
        except:
            pass
        return motd

    def getDockerId(self):
        try:
            f = open("/proc/self/cgroup")
            cgroup = f.read()
            m = self.cgroupPattern.search(cgroup)
            if m:
                return m.group(1)
        except:
            pass
        return ""


    def shutdown(self):
        self.closed = True
        self.logger.warn("shutdown supercast")
        self.connection.shutdown()

    def eventToState(self, event):
        if isinstance(event, events.ProcessStateEvent):
            return EVENTS_TO_STATES[event.__class__]
        return None

    def eventToPid(self, event):
        if isinstance(event, events.ProcessStateEvent):
            for k, v in event.get_extra_values():
                if "pid" == k:
                    return v
        return 0


class DoNothingRpc:
    pass


rpc = DoNothingRpc()
supercast = None

def make_supercast(supervisord, urls, environment="dev", subEnv="", clusterId="", returnProxy="", logfile="supercast.log", fixSignalableStates=True):
    """Sets up supercast and returns a dummy rpc interface.
    expects config parmeters like this:

    [rpcinterface:supercast]
    supervisor.rpcinterface_factory = supercast.make_supercast
    urls=ws://frontend1.company.com:12345/supervisor-updates,ws://frontend1.company.com:12345/supervisor-updates
    environment=Production
    subEnv=SpecialOps
    clusterId=cluster1
    returnProxy=proxy1.company.com:8080
    logfile=supercast.log"""

    global supercast

    if supercast and supercast.supervisord != supervisord:
        # looks like supervisord was restarted
        # The existing supercast instance will not get any more events so clean up and start over
        supercast.shutdown()
        supercast = None

    # this method will be called once for every external interface in the supervisor config file
    # but we only want to set this up once
    if not supercast:
        # use python logging to a separate file rather than messing with supervisors own logging implementation
        fh = RotatingFileHandler(logfile, maxBytes=50 * 1024 * 1024, backupCount=2)
        fh.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(message)s'))
        logger = logging.getLogger()
        logger.setLevel(logging.INFO)
        logger.addHandler(fh)
        logger.info("Supercast plugin starting.")

        # Create supercast itself
        host = socket.gethostname()
        urls = urls.split(",")
        urlIndex = random.randint(0, len(urls) - 1)
        supercast = Supercast(supervisord, host, environment.strip(), subEnv.strip(), urls, urlIndex, clusterId.strip(), returnProxy.strip(), logger)

    if fixSignalableStates:
        rpcinterface.SupervisorNamespaceRPCInterface.signalProcess = signalProcessProperly

    # return a dummy rpc plugin
    return rpc


# While we're here lets monkey-patch the existing rpc interface so we can signal stopping processes
def signalProcessProperly(self, name, signal):
    """ Send an arbitrary UNIX signal to the process named by name
    Monkeypatched by supercast so that it will send signals to
    STOPPING processes - enjoy"""

    self._update('signalProcess')

    group, process = self._getGroupAndProcess(name)

    if process is None:
        group_name, process_name = split_namespec(name)
        return self.signalProcessGroup(group_name, signal=signal)

    try:
        sig = signal_number(signal)
    except ValueError:
        raise RPCError(Faults.BAD_SIGNAL, signal)

    if process.get_state() not in (states.ProcessStates.RUNNING,
                                   states.ProcessStates.STARTING,
                                   states.ProcessStates.STOPPING):
        raise RPCError(Faults.NOT_RUNNING, name)

    msg = process.signal(sig)

    if not msg is None:
        raise RPCError(Faults.FAILED, msg)

    return True





