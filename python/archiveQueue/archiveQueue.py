#!/usr/bin/env python

### import Cohesity python module
from pyhesity import *
from datetime import datetime

### command line arguments
import argparse
parser = argparse.ArgumentParser()
parser.add_argument('-v', '--vip', type=str, required=True)
parser.add_argument('-u', '--username', type=str, required=True)
parser.add_argument('-d', '--domain', type=str, default='local')
parser.add_argument('-o', '--canceloutdated', action='store_true')
parser.add_argument('-q', '--cancelqueued', action='store_true')
parser.add_argument('-a', '--cancelall', action='store_true')
parser.add_argument('-n', '--numruns', type=int, default=500)
parser.add_argument('-s', '--units', type=str, choices=['MiB', 'GiB'], default='MiB')
args = parser.parse_args()

vip = args.vip
username = args.username
domain = args.domain
canceloutdated = args.canceloutdated
cancelqueued = args.cancelqueued
cancelall = args.cancelall
numruns = args.numruns
units = args.units

### authenticate
apiauth(vip, username, domain)

multiplier = 1024 * 1024
if units.lower() == 'gib':
    multiplier = 1024 * 1024 * 1024

finishedStates = ['kCanceled', 'kSuccess', 'kFailure', 'kWarning']

now = datetime.now()
dateString = now.strftime("%m-%d-%Y")
nowUsecs = dateToUsecs(now.strftime("%Y-%m-%d %H:%M:%S"))

cluster = api('get', 'cluster')
outfileName = 'ArchiveQueue-%s-%s.csv' % (cluster['name'], dateString)
f = open(outfileName, 'w')
f.write('JobName,RunDate,%s Transferred\n' % units)

runningTasks = {}

# for each active job
jobs = sorted(api('get', 'protectionJobs'), key=lambda j: j['name'].lower())
for job in jobs:
    if 'isDeleted' not in job:  # and ('isActive' not in job or job['isActive'] is not False):
        jobId = job['id']
        jobName = job['name']
        print("Getting tasks for %s" % jobName)
        # find runs with unfinished archive tasks
        endUsecs = nowUsecs
        while(1):
            runs = [r for r in api('get', 'protectionRuns?jobId=%s&numRuns=%s&endTimeUsecs=%s&excludeTasks=true' % (jobId, numruns, endUsecs)) if 'endTimeUsecs' not in r['backupRun']['stats'] or r['backupRun']['stats']['endTimeUsecs'] < endUsecs]
            if len(runs) > 0:
                endUsecs = runs[-1]['backupRun']['stats']['startTimeUsecs']
            else:
                break
            if runs is not None:
                runs = sorted(runs, key=lambda r: r['backupRun']['stats']['startTimeUsecs'])
                for run in runs:
                    runStartTimeUsecs = run['backupRun']['stats']['startTimeUsecs']
                    if 'copyRun' in run:
                        for copyRun in run['copyRun']:
                            # store run details in dictionary
                            if copyRun['status'] not in finishedStates and copyRun['target']['type'] == 'kArchival':
                                thisrun = api('get', '/backupjobruns?allUnderHierarchy=true&exactMatchStartTimeUsecs=%s&id=%s' % (runStartTimeUsecs, jobId))
                                if 'activeTasks' in thisrun[0]['backupJobRuns']['protectionRuns'][0]['copyRun']:
                                    for task in thisrun[0]['backupJobRuns']['protectionRuns'][0]['copyRun']['activeTasks']:
                                        # for task in thisrun[0]['backupJobRuns']['protectionRuns'][0]['copyRun']['activeTasks']:
                                        if task['snapshotTarget']['type'] == 3:
                                            # determine if run is now older than the intended retention
                                            noLongerNeeded = ''
                                            cancelling = ''
                                            if cancelall is True:
                                                cancel = True
                                            else:
                                                cancel = False
                                            daysToKeep = task['retentionPolicy']['numDaysToKeep']
                                            usecsToKeep = daysToKeep * 1000000 * 86400
                                            timePassed = nowUsecs - runStartTimeUsecs
                                            if timePassed > usecsToKeep:
                                                noLongerNeeded = "NO LONGER NEEDED"
                                                if canceloutdated is True:
                                                    cancel = True
                                            transferred = 0
                                            if 'archivalInfo' in task:
                                                if 'logicalBytesTransferred' in task['archivalInfo']:
                                                    transferred = task['archivalInfo']['logicalBytesTransferred']
                                            if transferred == 0 and cancelqueued is True:
                                                cancel = True
                                            if cancel is True:
                                                cancelling = 'Cancelling'
                                                cancelTaskParams = {
                                                    "copyTaskUid": {
                                                        "clusterIncarnationId": task['taskUid']['clusterIncarnationId'],
                                                        "id": task['taskUid']['objectId'],
                                                        "clusterId": task['taskUid']['clusterId']
                                                    },
                                                    "jobId": jobId
                                                }
                                                result = api('post', 'protectionRuns/cancel/%s' % jobId, cancelTaskParams)
                                            unitstransferred = round(float(transferred) / multiplier, 2)
                                            print('                       %s:  %s %s transferred %s %s' % (usecsToDate(runStartTimeUsecs), unitstransferred, units, noLongerNeeded, cancelling))
                                            f.write('%s,%s,%s\n' % (jobName, (usecsToDate(runStartTimeUsecs)), unitstransferred))
f.close()
print("output saved to %s" % outfileName)
