# Oyente

**Note: The tool is currently under development, please report any bugs you may find.**

## 516 Development

* Use ubuntu to develop
* Install docker
* Open remote API for dockerd:
    https://success.docker.com/article/how-do-i-enable-the-remote-api-for-dockerd
* Install oyente image
    https://hub.docker.com/r/hrishioa/oyente/
* Install pycharm professional version
* Set oytent docker as project intepreter in Pycharm:
    https://www.jetbrains.com/help/pycharm/using-docker-as-a-remote-interpreter.html
* In Pycharm oyente.py run configuration, add z3 path:
    PYTHONPATH=/home/oyente/dependencies/z3-z3-4.4.1/build
* Run oyente.py /home/oyente/oyente/greeter.sol in Pycharm. Should able to see:
```log
47f9b1891177:/home/oyente/dependencies/venv/bin/python -u /opt/project/oyente.py /home/oyente/oyente/greeter.sol
Contract greeter:
Running, please wait...
	============ Results ===========
	  CallStack Attack: 	 False
	  Concurrency Bug: 	 False
	  Time Dependency: 	 False
	  Reentrancy bug exists: False
	====== Analysis Completed ======

Process finished with exit code 0
```
## Quick Start

A container with the dependencies set up and the blockchain snapshot installed can be found [here](https://hub.docker.com/r/hrishioa/oyente/).

To open the container, install docker and run:

```docker pull hrishioa/oyente && docker run -i -t hrishioa/oyente```

To evaluate the greeter contract Inside the container, run:

```cd /home/oyente/oyente && source ../dependencies/venv/bin/activate && python oyente.py greeter.sol```

and you are done!

## Dependencies

1. solc and disasm from [go-ethereum](https://github.com/ethereum/go-ethereum)
2. [z3](https://github.com/Z3Prover/z3/releases) Theorem Prover

## Evaluating Ethereum Contracts

```python oyente.py <contract filename>```

And that's it! Run ```python oyente.py --help``` for a list of options.

## Paper

The accompanying paper explaining the bugs detected by the tool can be found [here](http://www.comp.nus.edu.sg/~loiluu/papers/oyente.pdf).

## Miscellaneous Utilities

A collection of the utilities that were developed for the paper are in `Misc_Utils`. Use them at your own risk - they have mostly been disposable.

1. `generate-graphs.py` - Contains a number of functions to get statistics from contracts.
2. `get_source.py` - The *get_contract_code* function can be used to retrieve contract source from [EtherScan](https://etherscan.io)
3. `transaction_scrape.py` - Contains functions to retrieve up-to-date transaction information for a particular contract.

## Benchmarks

Note: This is an improved version of the tool used for the paper. Benchmarks are not for direct comparison.

To run the benchmarks, it is best to use the docker container as it includes the blockchain snapshot necessary.
In the container, run `batch_run.py` after activating the virtualenv. Results are in `results.json` once the benchmark completes.

The benchmarks take a long time and a *lot* of RAM in any but the largest of clusters, beware.

#### Known Issues
If you encounter the `unhashable instance` error, please add the following to your `class AstRef(Z3PPObject):` in `/usr/lib/python2.7/dist-packages/z3.py`:
```
def __hash__(self):
        return self.hash()
```
The latest version of Z3 does support this, but some previous version does not.
