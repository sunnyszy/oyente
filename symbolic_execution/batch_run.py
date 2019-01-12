import json
import glob
# from tqdm import tqdm
import os
import sys
import urllib2
import time

contract_dir = '/opt/project/contract_data'

cfiles = glob.glob(contract_dir+'/contract*.json')

cjson = {}

print "Loading contracts..."

for cfile in cfiles:
	cjson.update(json.loads(open(cfile).read()))

results = {}
missed = []

print "Running analysis..."

contracts = cjson.keys()

if os.path.isfile('results.json'):
	old_res = json.loads(open('results.json').read())
	old_res = old_res.keys()
	contracts = [c for c in contracts if c not in old_res]

cores=0
job=0

if len(sys.argv)>=3:
	cores = int(sys.argv[1])
	job = int(sys.argv[2])
	contracts = contracts[(len(contracts)/cores)*job:(len(contracts)/cores)*(job+1)]
	print "Job %d: Running on %d contracts..." % (job, len(contracts))
cntnum = 0
start_time = time.time()
for c in contracts:
	with open('tmp_'+str(job)+'.evm','w') as of:
		# print "Out: "+cjson[c][1][2:]
		of.write(cjson[c][1][2:]+"\0")
	os.system('python oyente.py tmp_'+str(job)+'.evm -j -b')
	try:
		results[c] = json.loads(open('tmp_'+str(job)+'.evm.json').read())
	except:
		missed.append(c)
	if cntnum == 2:
		break
	cntnum += 1
with open('results_'+str(job)+'.json', 'w') as of:
	of.write(json.dumps(results,indent=1))
with open('missed_'+str(job)+'.json', 'w') as of:
	of.write(json.dumps(missed,indent=1))
	# urllib2.urlopen('https://dweet.io/dweet/for/oyente-%d-%d?completed=%d&missed=%d&remaining=%d' % (job,cores,len(results),len(missed),len(contracts)-len(results)-len(missed)))
print "Completed."
duration = time.time() - start_time
with open('time_'+str(job)+'.txt', 'w') as of:
	of.write(str(duration))
