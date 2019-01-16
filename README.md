# Supercast
A Supervisor plugin to push all process details and state changes to a central service.

Allow a single application to monitor a huge number of processes across hundreds or thousands of hosts.


## Usage

Place the supercast.py file somewhere on the supervisor daemon's PYTHONPATH.

Also add the websocket-client module and make it available.

```
    pip install websocket-client
```

Then add the following to the supervisor.conf (only the first 3 lines are required - the rest have defaults)
```
[rpcinterface:supercast]
supervisor.rpcinterface_factory = supercast.make_supercast
urls=ws://frontend1.company.com:12345/supervisor-updates,ws://frontend1.company.com:12345/supervisor-updates
environment=Production
subEnv=SpecialOps
clusterId=cluster1
returnProxy=proxy1.company.com:8080
logfile=supercast.log
```

You should also ensure that the `identifier` configured under the `[supervisord]` section in the `supervisor.conf` is 
unique across your entire infrastructure.

###### urls
A comma separated list of websocket endpoints which supercast will try to connect to and send status 
information.  It'll pick one at random and then iterate through them in a round-robin fashion whenever the connection
fails.


###### environment
Specifies the envronment of all processes running under this supervisor. 
It's simply a string sent to the server and may be used to categorise supervisors in a UI or front end.
Defaults to 'dev'

###### subEnv
Specifies a sub-environment to further categorise the processes running under this supervisor.
Defaults to an empty string.

###### clusterId
Allows you to specify the docker cluster or similar information if required by the server process.  
Defaults to an empty string.

###### returnProxy
Tells the server process about any proxy required to connect to this supervisor rpc interface.  This may be required
for supervisors running under some docker configurations.  Defaults to empty string

###### logfile
Where to put the Supercast logs.  Defaults to `supercast.log`

## How it works
### Overview
This plugin will attempt to maintain a websocket connection to one the configured urls.
It will then send json messages containing full details of the supervisor daemon, the host and each process.
The messages are sent on connection and repeated whenever any state changes as well as on a regular schedule.
If the connection breaks it will automatically reconnect to the next configured destination in round-robin fashion.

The server can display the current state of all supervisors and processes in one place and can control processes
by connecting back to the individual supervisor xml-rpc interfaces.

The reference server implementation has a number of identical redundant servers connected by a shared memory grid.  
This allows updates to be received from supervisors on any server and the data is shared with all other servers in the cluster.

Normally the server can detect disconnections and mark that particular host as lost unless a shutdown status update was received.  
When the supervisor re-connects to the cluster it is marked as running again.  Supervisors that don't connect for a long time can
be deleted unless they are not expected to be normally present.

If a server cluster node goes down then typically all supervisors will reconnect to other nodes within a few seconds
and users will not notice. 
To allow for stuck or dead supervisor data to be cleaned up the supercast plugin will re-send all state at least every hour.
The servers can then timestamp each update and will purge any data that has not been updated for longer than this.


### Websocket Messages

Messages from supercast to the websocket server consist of a single json object with 4 possible members.

There are currently no messages sent from the server to the supervisor over the websocket connection.  All control and 
log tailing is done via the xml-rpc interface.

#### supervisor
This is the first message sent immediately after connection. It's also sent whenever there are any changes and at
least once per hour.  

example message:
```
{"supervisor": 
  {
    "supervisorid": "londondev1.company.com", 
    "updateTime": 1538650345269.77, 
    "since": 1534949285260.078, 
    "motd": "welcome to londondev1 ...", 
    "supervisorpid": 7444, 
    "subEnv": "", 
    "statename": "RUNNING", 
    "state": 1, 
    "host": "londondev1.company.com", 
    "rpcport": 9009, 
    "supervisorversion": "3.3.1", 
    "arch": "x86_64", 
    "env": "dev", 
    "osversion": "#1 SMP ...", 
    "os": "Linux-2.6.xx ...", 
    "processor": "x86_64", 
    "clusterId": "",
    "dockerId": "",
    "returnProxy": "",
    "configadded": [], 
    "configupdated": [], 
    "configremoved": [],
    "configError": null
  }
}
```

#### process
This message is sent once for each process after connection following the supervisor message, when there are changes 
and at least once per hour.

example message:
```
{"process": 
  {
    "updateTime": 1538650029151.118, 
    "startsecs": 30, 
    "uid": 2000455, 
    "pid": 11213, 
    "stopsignal": 15, 
    "exitstatus": 0, 
    "childpids": "", 
    "group": "myscripts", 
    "since": 1538650027990.5442, 
    "start": 1538650027990.5442, 
    "state": 20, 
    "env": "dev", 
    "username": "appuser", 
    "autostart": true, 
    "stderr_logfile": null, 
    "stop": 1538650026988.152, 
    "host": "londondev1.company.com", 
    "spawnerr": "", 
    "exitcodes": "[0, 2]", 
    "supervisorid": "londondev1.company.com", 
    "name": "myscript", 
    "subEnv": "", 
    "statename": "RUNNING", 
    "command": "/usr/bin/python myscript.py", 
    "startretries": 3, 
    "stopwaitsecs": 60, 
    "directory": "/usr/local/myscript", 
    "stdout_logfile": "/logs/myscript.log",
    "environmentVars": {"key": "value"}
  }
}
```

The supervisorid, host, env and subEnv of the process will match the supervisor message.  Having different values of these
parameters on processes running under the same supervisor daemon is not currently supported - they are only repeated
in the process message for convenience.



#### updateComplete
This message is sent once following the supervisor message and the complete set of process messages after connection.
It indicates to the server that the complete set of information has now been sent over the current connection.  
The server should then clean-up any old process details received via a previous connection that have not been re-sent.
e.g. processes that were removed from supervisor while it was disconnected from the server.

```
{"updateComplete": true }
```


#### deleteGroup
This is sent whenever a group is deleted from the supervisor daemon.

```
{"deleteGroup": "myscripts" }
```

Note that individual processes are never deleted from supervisor.  
To load changes to a process config the entire group is stopped, deleted and re-added.



## Future Directions

* Most of the recent changes have been to add more information about the host and processes.  
It is likely that this trend will continue.
* Some way to send commands to the supervisor via the websocket connection.  This would avoid the xml-rpc interface 
and issues with proxies across network domains and into docker clusters.  
For clustered servers this will probably involve forwarding commands across the cluster
to reach the connected node. Streaming log updates may need an alternative route.
* Code tidy up - This code has worked very well for years
in our deployment but much of it doesn't follow any recommended python style.
* checking for config changes could be made more efficient
* We have a huge list of improvements we'd like to make to supervisor itself - but unfortunately very little time


## History

Created and maintained by Mike Gould at Tudor from 2016 to present


## Licence











