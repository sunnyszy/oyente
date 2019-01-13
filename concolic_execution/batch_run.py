import json
import glob
# from tqdm import tqdm
import os
import sys
import urllib2
import time

contract_dir = '../contract_data'

cfiles = glob.glob(contract_dir + '/contract*.json')

cjson = {}

print "Loading contracts..."

for cfile in cfiles:
    cjson.update(json.loads(open(cfile).read()))

results = {}

print "Running analysis..."

contracts = cjson.keys()

if os.path.isfile('results.json'):
    old_res = json.loads(open('results.json').read())
    old_res = old_res.keys()
    contracts = [c for c in contracts if c not in old_res]

cores = 0
job = 0


if len(sys.argv) >= 3:
    cores = int(sys.argv[1])
    job = int(sys.argv[2])
    contracts = contracts[(len(contracts) / cores) * job:(len(contracts) / cores) * (job + 1)]
    print "Job %d: Running on %d contracts..." % (job, len(contracts))
cntnum = 0
start_time = time.time()
for c in contracts:
    # c = '0x00c06521148cf463d4b51552d86237918243e9b4'
    print "contract: " + c
    with open('tmp_' + c + '.evm', 'w') as of:
        # print "Out: "+cjson[c][1][2:]
        of.write(cjson[c][1][2:] + "\0")
    # exit(0)
    os.system('python2 oyente.py tmp_' + c + '.evm -j -b')
    try:
        results[c] = json.loads(open('tmp_' + c + '.evm.json').read())
    except:
        results[c] = {}
    # if cntnum == 2:
    with open('results_' + c + '.json', 'w') as of_result:
        of_result.write(json.dumps(results, indent=1))
        # break
        cntnum += 1
print "Completed."
