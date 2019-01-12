#!/usr/bin/env bash
#docker run -it --rm -v /data/zhenyus/oyente:/opt/project hrishioa/oyente
#export PYTHONPATH=/home/oyente/dependencies/z3-z3-4.4.1/build
CORES=76
pwd=$(pwd)
for i in `seq 0 $(( $CORES - 1))`; do python ${pwd}/batch_run.py $CORES $i &> $i.log & done