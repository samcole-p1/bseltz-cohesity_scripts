#!/usr/bin/env python
"""cluster protection runs report"""

# import pyhesity wrapper module
from pyhesity import *
from datetime import datetime
import codecs

# command line arguments
import argparse
parser = argparse.ArgumentParser()
parser.add_argument('-v', '--vip', type=str, required=True, action='append')
parser.add_argument('-u', '--username', type=str, required=True)
parser.add_argument('-d', '--domain', type=str, default='local')
parser.add_argument('-i', '--useApiKey', action='store_true')
parser.add_argument('-pwd', '--password', type=str, default=None)
parser.add_argument('-np', '--noprompt', action='store_true')
parser.add_argument('-m', '--mfacode', type=str, default=None)
parser.add_argument('-y', '--days', type=int, default=None)
parser.add_argument('-x', '--unit', type=str, choices=['KiB', 'MiB', 'GiB', 'TiB'], default='GiB')
parser.add_argument('-t', '--objecttype', type=str, default=None)
parser.add_argument('-l', '--includelogs', action='store_true')
parser.add_argument('-n', '--numruns', type=int, default=500)
args = parser.parse_args()

vips = args.vip
username = args.username
domain = args.domain
useApiKey = args.useApiKey
password = args.password
noprompt = args.noprompt
mfacode = args.mfacode
days = args.days
unit = args.unit
objecttype = args.objecttype
includelogs = args.includelogs
numruns = args.numruns

if days is not None:
    daysBackUsecs = timeAgo(days, 'days')

multiplier = 1024 * 1024 * 1024
if unit == 'TiB':
    multiplier = 1024 * 1024 * 1024 * 1024
elif unit == 'MiB':
    multiplier = 1024 * 1024
elif unit == 'KiB':
    multiplier = 1024

now = datetime.now()
nowUsecs = dateToUsecs(now.strftime("%Y-%m-%d %H:%M:%S"))

# output file
dateString = now.strftime("%Y-%m-%d")
outfile = 'protectionRunsReport-%s.tsv' % dateString
f = codecs.open(outfile, 'w')
f.write('Start Time\tEnd Time\tDuration\tstatus\tslaStatus\tsnapshotStatus\tobjectName\tsourceName\tgroupName\tpolicyName\tObject Type\tbackupType\tSystem Name\tLogical Size $unit\tData Read $unit\tData Written $unit\tOrganization Name\n')

for vip in vips:
    # authenticate
    apiauth(vip=vip, username=username, domain=domain, password=password, useApiKey=useApiKey, prompt=(not noprompt), mfaCode=mfacode)

    # exit if not authenticated
    if apiconnected() is False:
        print('authentication failed')
        continue

    cluster = api('get', 'cluster')
    jobs = api('get', 'data-protect/protection-groups?isDeleted=false&includeTenants=true', v=2)
    sources = api('get', 'protectionSources/registrationInfo?includeApplicationsTreeInfo=false')
    policies = api('get', 'data-protect/policies', v=2)

    if jobs['protectionGroups'] is None:
        continue

    for job in sorted(jobs['protectionGroups'], key=lambda job: job['name'].lower()):

        if len(job['permissions']) > 0 and 'name' in job['permissions'][0]:
            tenant = job['permissions'][0]['name']
            print('%s (%s)' % (job['name'], tenant))
        else:
            tenant = ''
            print('%s' % job['name'])
        environment = job['environment']
        if objecttype is None or environment == objecttype:
            policy = [p for p in policies['policies'] if p['id'] == job['policyId']]
            if policy is not None and len(policy) > 0:
                policyName = policy[0]['name']
            else:
                policyName = '-'
            endUsecs = nowUsecs
            while 1:
                runs = api('get', 'data-protect/protection-groups/%s/runs?numRuns=%s&endTimeUsecs=%s&includeTenants=true&includeObjectDetails=true' % (job['id'], numruns, endUsecs), v=2)
                if len(runs['runs']) > 0:
                    if 'localBackupInfo' in runs['runs'][-1]:
                        endUsecs = runs['runs'][-1]['localBackupInfo']['startTimeUsecs'] - 1
                    elif 'originalBackupInfo' in runs['runs'][-1]:
                        endUsecs = runs['runs'][-1]['originalBackupInfo']['startTimeUsecs'] - 1
                    else:
                        endUsecs = runs['runs'][-1]['archivalInfo']['archivalTargetResults'][0]['startTimeUsecs'] - 1
                else:
                    break
                for run in runs['runs']:
                    try:
                        if 'localBackupInfo' in run:
                            backupInfo = run['localBackupInfo']
                            snapshotInfo = 'localSnapshotInfo'
                        elif 'originalBackupInfo' in run:
                            backupInfo = run['originalBackupInfo']
                            snapshotInfo = 'originalBackupInfo'
                        else:
                            continue
                        status = backupInfo['status']
                        localSources = {}
                        if 'isLocalSnapshotsDeleted' not in run or run['isLocalSnapshotsDeleted'] is False:
                            runType = backupInfo['runType']
                            if includelogs or runType != 'kLog':
                                runStartTime = usecsToDate(backupInfo['startTimeUsecs'])
                                if days is not None and daysBackUsecs > backupInfo['startTimeUsecs']:
                                    break
                                if 'isSlaViolated' in backupInfo and backupInfo['isSlaViolated'] is True:
                                    slaStatus = 'Missed'
                                else:
                                    slaStatus = 'Met'
                                print("    %s  %s" % (runStartTime, status))
                                for object in run['objects']:
                                    if environment in ['kOracle', 'kSQL'] and object['object']['objectType'] == 'kHost':
                                        localSources[object['object']['id']] = object['object']['name']
                                for object in run['objects']:
                                    objectName = object['object']['name']
                                    registeredSourceName = objectName
                                    if environment not in ['kOracle', 'kSQL'] or object['object']['objectType'] != 'kHost':
                                        if 'sourceId' in object['object']:
                                            if environment in ['kOracle', 'kSQL']:
                                                registeredSourceName = localSources.get(object['object']['sourceId'], objectName)
                                            else:

                                                registeredSource = [s for s in sources['rootNodes'] if s['rootNode']['id'] == object['object']['sourceId']]
                                                if registeredSource is not None and len(registeredSource) > 0:
                                                    registeredSourceName = registeredSource[0]['rootNode']['name']

                                        objectStatus = object[snapshotInfo]['snapshotInfo']['status']
                                        if objectStatus == 'kSuccessful':
                                            objectStatus = 'kSuccess'
                                        objectStartTime = usecsToDate(object[snapshotInfo]['snapshotInfo']['startTimeUsecs'])
                                        objectEndTime = None
                                        objectDurationSeconds = int((nowUsecs - object[snapshotInfo]['snapshotInfo']['startTimeUsecs']) / 1000000)
                                        if 'endTimeUsecs' in object[snapshotInfo]['snapshotInfo']:
                                            objectEndTime = usecsToDate(object[snapshotInfo]['snapshotInfo']['endTimeUsecs'])
                                            objectDurationSeconds = int((object[snapshotInfo]['snapshotInfo']['endTimeUsecs'] - object[snapshotInfo]['snapshotInfo']['startTimeUsecs']) / 1000000)
                                        objectLogicalSizeBytes = round(object[snapshotInfo]['snapshotInfo']['stats'].get('logicalSizeBytes', 0) / multiplier, 1)
                                        objectBytesWritten = round(object[snapshotInfo]['snapshotInfo']['stats'].get('bytesWritten', 0) / multiplier, 1)
                                        objectBytesRead = round(object[snapshotInfo]['snapshotInfo']['stats'].get('bytesRead', 0) / multiplier, 1)
                                        print('        %s' % objectName)
                                        f.write('%s\t%s\t%s\t%s\t%s\tActive\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n' % (objectStartTime, objectEndTime, objectDurationSeconds, objectStatus, slaStatus, objectName, registeredSourceName, job['name'], policyName, environment, runType, cluster['name'], objectLogicalSizeBytes, objectBytesRead, objectBytesWritten, tenant))
                    except Exception:
                        pass
f.close()
print('\nOutput saved to %s\n' % outfile)
