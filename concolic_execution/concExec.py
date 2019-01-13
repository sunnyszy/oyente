from z3 import *
from vargenerator import *
import tokenize
import signal
from tokenize import NUMBER, NAME, NEWLINE
from basicblock import BasicBlock
from analysis import *
from utils import *
from math import *
import time
from global_params import *
import sys
import atexit
import random

results = {}

if len(sys.argv) >= 12:
    IGNORE_EXCEPTIONS = int(sys.argv[2])
    REPORT_MODE = int(sys.argv[3])
    PRINT_MODE = int(sys.argv[4])
    DATA_FLOW = int(sys.argv[5])
    DEBUG_MODE = int(sys.argv[6])
    CHECK_CONCURRENCY_FP = int(sys.argv[7])
    TIMEOUT = int(sys.argv[8])
    UNIT_TEST = int(sys.argv[9])
    GLOBAL_TIMEOUT = int(sys.argv[10])
    PRINT_PATHS = int(sys.argv[11])

if REPORT_MODE:
    report_file = sys.argv[1] + '.report'
    rfile = open(report_file, 'w')

count_unresolved_jumps = 0
gen = None  # to generate names for symbolic variables

end_ins_dict = {}  # capturing the last statement of each basic block
instructions = {}  # capturing all the instructions, keys are corresponding addresses
jump_type = {}  # capturing the "jump type" of each basic block
vertices = {}
edges = {}

"""
concolic flag
"""
all_linear = True
all_locs_definite = True
forcing_ok = True


money_flow_all_paths = []
reentrancy_all_paths = []
earlypay_all_paths = []
data_flow_all_paths = [[], []]  # store all storage addresses
path_conditions = []  # store the path condition corresponding to each path in money_flow_all_paths
all_gs = []  # store global variables, e.g. storage, balance of all paths
total_no_of_paths = 0

c_name = sys.argv[1]
if (len(c_name) > 5):
    c_name = c_name[4:]
set_cur_file(c_name)

# Z3 solver
solver = Solver()
solver.set("timeout", TIMEOUT)

CONSTANT_ONES_159 = BitVecVal((1 << 160) - 1, 256)

if UNIT_TEST == 1:
    try:
        result_file = open(sys.argv[13], 'r')
    except:
        if PRINT_MODE: print "Could not open result file for unit test"
        exit()

log_file = open(sys.argv[1] + '.log', "w")


# A simple function to compare the end stack with the expected stack
# configurations specified in a test file
def compare_stack_unit_test(stack):
    if UNIT_TEST != 1:
        return
    try:
        size = int(result_file.readline())
        content = result_file.readline().strip('\n')
        if size == len(stack) and str(stack) == content:
            if PRINT_MODE: print "PASSED UNIT-TEST"
        else:
            if PRINT_MODE: print "FAILED UNIT-TEST"
            if PRINT_MODE: print "Expected size %d, Resulted size %d" % (size, len(stack))
            if PRINT_MODE: print "Expected content %s \nResulted content %s" % (content, str(stack))
    except Exception as e:
        if PRINT_MODE: print "FAILED UNIT-TEST"
        if PRINT_MODE: print e.message


def handler(signum, frame):
    raise Exception("timeout")


def main():
    start = time.time()
    signal.signal(signal.SIGALRM, handler)
    signal.alarm(GLOBAL_TIMEOUT)

    print "Running, please wait..."

    print "\t============ Results ==========="

    if PRINT_MODE:
        print "Checking for Callstack attack..."

    run_callstack_attack()
    try:
        build_cfg_and_analyze()
        if PRINT_MODE:
            print "Done Symbolic execution"
    except Exception as e:
        print "Exception - " + str(e)
        print "Time out"
        raise
    signal.alarm(0)

    if REPORT_MODE:
        rfile.write(str(total_no_of_paths) + "\n")

    print "detecting..."
    detect_money_concurrency()
    detect_time_dependency()
    run_early_pay_attack()
    stop = time.time()
    results['duration'] = time.time()-start
    if REPORT_MODE:
        rfile.write(str(stop - start))
        rfile.close()
    if DATA_FLOW:
        detect_data_concurrency()
        detect_data_money_concurrency()
    if PRINT_MODE:
        print "Results for Reentrancy Bug: " + str(reentrancy_all_paths)
    reentrancy_bug_found = any([v for sublist in reentrancy_all_paths for v in sublist])
    print "\t  Reentrancy bug exists: %s" % str(reentrancy_bug_found)
    results['reentrancy'] = reentrancy_bug_found


def closing_message():
    print "\t====== Analysis Completed ======"
    if len(sys.argv) > 12:
        with open(sys.argv[12], 'w') as of:
            of.write(json.dumps(results, indent=1))
        print "Wrote results to %s." % sys.argv[12]


atexit.register(closing_message)


def build_cfg_and_analyze():
    with open(sys.argv[1], 'r') as disasm_file:
        disasm_file.readline()  # Remove first line
        tokens = tokenize.generate_tokens(disasm_file.readline)
        collect_vertices(tokens)
        construct_bb()
        construct_static_edges()
        full_concolic_exec()  # jump targets are constructed on the fly


# Detect if a money flow depends on the timestamp
def detect_time_dependency():
    TIMESTAMP_VAR = "IH_s"
    is_dependant = False
    index = 0
    if PRINT_PATHS:
        print "ALL PATH CONDITIONS"
    for cond in path_conditions:
        index += 1
        if PRINT_PATHS:
            print "PATH " + str(index) + ": " + str(cond)
        list_vars = []
        for expr in cond:
            if is_expr(expr):
                list_vars += get_vars(expr)
        set_vars = set(i.decl().name() for i in list_vars)
        if TIMESTAMP_VAR in set_vars:
            is_dependant = True
            break

    print "\t  Time Dependency: \t %s" % is_dependant
    results['time_dependency'] = is_dependant

    if REPORT_MODE:
        file_name = sys.argv[1].split("/")[len(sys.argv[1].split("/")) - 1].split(".")[0]
        report_file = file_name + '.report'
        with open(report_file, 'w') as rfile:
            if is_dependant:
                rfile.write("yes\n")
            else:
                rfile.write("no\n")


# detect if two paths send money to different people
def detect_money_concurrency():
    n = len(money_flow_all_paths)
    for i in range(n):
        if PRINT_MODE: print "Path " + str(i) + ": " + str(money_flow_all_paths[i])
        if PRINT_MODE: print all_gs[i]
    i = 0
    false_positive = []
    concurrency_paths = []
    for flow in money_flow_all_paths:
        i += 1
        if len(flow) == 1:
            continue  # pass all flows which do not do anything with money
        for j in range(i, n):
            jflow = money_flow_all_paths[j]
            if len(jflow) == 1:
                continue
            if is_diff(flow, jflow):
                concurrency_paths.append([i - 1, j])
                if CHECK_CONCURRENCY_FP and \
                        is_false_positive(i - 1, j, all_gs, path_conditions) and \
                        is_false_positive(j, i - 1, all_gs, path_conditions):
                    false_positive.append([i - 1, j])

    # if PRINT_MODE: print "All false positive cases: ", false_positive
    if PRINT_MODE: print "Concurrency in paths: ", concurrency_paths
    if len(concurrency_paths) > 0:
        print "\t  Concurrency found in paths: %s" + str(concurrency_paths)
        results['concurrency'] = True
    else:
        print "\t  Concurrency Bug: \t False"
        results['concurrency'] = False
    if REPORT_MODE:
        rfile.write("number of path: " + str(n) + "\n")
        # number of FP detected
        rfile.write(str(len(false_positive)) + "\n")
        rfile.write(str(false_positive) + "\n")
        # number of total races
        rfile.write(str(len(concurrency_paths)) + "\n")
        # all the races
        rfile.write(str(concurrency_paths) + "\n")


# Detect if there is data concurrency in two different flows.
# e.g. if a flow modifies a value stored in the storage address and
# the other one reads that value in its execution
def detect_data_concurrency():
    sload_flows = data_flow_all_paths[0]
    sstore_flows = data_flow_all_paths[1]
    concurrency_addr = []
    for sflow in sstore_flows:
        for addr in sflow:
            for lflow in sload_flows:
                if addr in lflow:
                    if not addr in concurrency_addr:
                        concurrency_addr.append(addr)
                    break
    if PRINT_MODE: print "data conccureny in storage " + str(concurrency_addr)


# detect if any change in a storage address will result in a different
# flow of money. Currently I implement this detection by
# considering if a path condition contains
# a variable which is a storage address.
def detect_data_money_concurrency():
    n = len(money_flow_all_paths)
    sstore_flows = data_flow_all_paths[1]
    concurrency_addr = []
    for i in range(n):
        cond = path_conditions[i]
        list_vars = []
        for expr in cond:
            list_vars += get_vars(expr)
        set_vars = set(i.decl().name() for i in list_vars)
        for sflow in sstore_flows:
            for addr in sflow:
                var_name = gen.gen_owner_store_var(addr)
                if var_name in set_vars:
                    concurrency_addr.append(var_name)
    if PRINT_MODE: print "Concurrency in data that affects money flow: " + str(set(concurrency_addr))


def print_cfg():
    for block in vertices.values():
        block.display()
    if PRINT_MODE: print str(edges)


# 1. Parse the disassembled file
# 2. Then identify each basic block (i.e. one-in, one-out)
# 3. Store them in vertices
def collect_vertices(tokens):
    global instructions, end_ins_dict, jump_type
    current_ins_address = 0
    last_ins_address = 0
    is_new_line = True
    current_block = 0
    current_line_content = ""
    wait_for_push = False
    is_new_block = False

    for tok_type, tok_string, (srow, scol), _, line_number in tokens:
        if wait_for_push is True:
            push_val = ""
            for ptok_type, ptok_string, _, _, _ in tokens:
                if ptok_type == NEWLINE:
                    is_new_line = True
                    current_line_content += push_val + ' '
                    instructions[current_ins_address] = current_line_content
                    if PRINT_MODE: print current_line_content
                    current_line_content = ""
                    wait_for_push = False
                    break
                try:
                    int(ptok_string, 16)
                    push_val += ptok_string
                except ValueError:
                    pass

            continue
        elif is_new_line is True and tok_type == NUMBER:  # looking for a line number
            last_ins_address = current_ins_address
            try:
                current_ins_address = int(tok_string)
            except ValueError:
                if PRINT_MODE: print "ERROR when parsing row %d col %d" % (srow, scol)
                quit()
            is_new_line = False
            if is_new_block:
                current_block = current_ins_address
                is_new_block = False
            continue
        elif tok_type == NEWLINE:
            is_new_line = True
            if PRINT_MODE: print current_line_content
            instructions[current_ins_address] = current_line_content
            current_line_content = ""
            continue
        elif tok_type == NAME:
            if tok_string == "JUMPDEST":
                if not (last_ins_address in end_ins_dict):
                    end_ins_dict[current_block] = last_ins_address
                current_block = current_ins_address
                is_new_block = False
            elif tok_string == "STOP" or tok_string == "RETURN" or tok_string == "SUICIDE":
                jump_type[current_block] = "terminal"
                end_ins_dict[current_block] = current_ins_address
            elif tok_string == "JUMP":
                jump_type[current_block] = "unconditional"
                end_ins_dict[current_block] = current_ins_address
                is_new_block = True
            elif tok_string == "JUMPI":
                jump_type[current_block] = "conditional"
                end_ins_dict[current_block] = current_ins_address
                is_new_block = True
            elif tok_string.startswith('PUSH', 0):
                wait_for_push = True
            is_new_line = False
        if tok_string != "=" and tok_string != ">":
            current_line_content += tok_string + " "

    if current_block not in end_ins_dict:
        if PRINT_MODE: print "current block: %d" % current_block
        if PRINT_MODE: print "last line: %d" % current_ins_address
        end_ins_dict[current_block] = current_ins_address

    if current_block not in jump_type:
        jump_type[current_block] = "terminal"

    for key in end_ins_dict:
        if key not in jump_type:
            jump_type[key] = "falls_to"


def construct_bb():
    global vertices, edges
    sorted_addresses = sorted(instructions.keys())
    size = len(sorted_addresses)
    for key in end_ins_dict:
        end_address = end_ins_dict[key]
        block = BasicBlock(key, end_address)
        if key not in instructions: continue
        block.add_instruction(instructions[key])
        i = sorted_addresses.index(key) + 1
        while i < size and sorted_addresses[i] <= end_address:
            block.add_instruction(instructions[sorted_addresses[i]])
            i += 1
        block.set_block_type(jump_type[key])
        vertices[key] = block
        edges[key] = []


def construct_static_edges():
    add_falls_to()  # these edges are static


def add_falls_to():
    global vertices, edges
    key_list = sorted(jump_type.keys())
    length = len(key_list)
    for i, key in enumerate(key_list):
        if jump_type[key] != "terminal" and jump_type[key] != "unconditional" and i + 1 < length:
            target = key_list[i + 1]
            edges[key].append(target)
            vertices[key].set_falls_to(target)


def get_init_global_state(path_conditions_and_vars):
    global I_vars, I_balance
    global I_constraint
    global_state = {"balance": {}}  # address is concrete
    global_state_concrete = {"balance": {}}

    # the address
    for new_var_name in ("Is", "Ia"):
        if new_var_name not in path_conditions_and_vars:
            new_var = BitVec(new_var_name, 256)
            path_conditions_and_vars[new_var_name] = new_var
            if new_var_name not in I_vars:
                I_vars[new_var_name] = random.randint(0, 2 ** 256 - 1)

    deposited_value = BitVec("Iv", 256)
    path_conditions_and_vars["Iv"] = deposited_value
    I_constraint.append(deposited_value <= 1e20)
    if "Iv" not in I_vars:
        # rough estimate upper bound.
        # See https://ethereum.stackexchange.com/questions/16825/is-there-a-max-amount-of-gas-per-transaction
        I_vars["Iv"] = random.randint(0, 1e20)

    # the balance
    init_is = BitVec("init_Is", 256)
    init_ia = BitVec("init_Ia", 256)

    constraint = (deposited_value >= BitVecVal(0, 256))
    path_conditions_and_vars["path_condition"].append(constraint)
    constraint = (init_is >= deposited_value)
    path_conditions_and_vars["path_condition"].append(constraint)
    constraint = (init_ia >= BitVecVal(0, 256))
    path_conditions_and_vars["path_condition"].append(constraint)

    # update the balances of the "caller" and "callee"

    new_var_name = 'balance_' + str(I_vars["Is"])
    global_state["balance"][new_var_name] = (init_is - deposited_value)
    if new_var_name not in I_balance:
        I_balance[new_var_name] = random.randint(0, 2 ** 256 - 1 - I_vars["Iv"])
    global_state_concrete["balance"][new_var_name] = I_balance[new_var_name]

    new_var_name = 'balance_' + str(I_vars["Ia"])
    global_state["balance"][new_var_name] = (init_ia + deposited_value)
    if new_var_name not in I_balance:
        I_balance[new_var_name] = random.randint(I_vars["Iv"], 2 ** 256 - 1)
    global_state_concrete["balance"][new_var_name] = I_balance[new_var_name]

    # the state of the current current contract
    global_state["Ia"] = {}
    global_state_concrete["Ia"] = {}
    # miu_i is always constant as address is always constant
    global_state["miu_i"] = 0

    return global_state, global_state_concrete


def full_concolic_exec():
    global all_linear, all_locs_definite, forcing_ok

    # init concrete flag
    all_linear, all_locs_definite, forcing_ok = True, True, True

    # init concrete trace stack
    concolic_stack = []
    global I_vars, I_gen, I_balance, I_store
    I_vars = {}  # init for specific var, e.g., Is
    I_gen = {}  # init for calldataload
    I_balance = {}  # init for global balance
    I_store = {}

    directed = 1
    while directed:
        try:
            directed, concolic_stack = instrumented_program(concolic_stack)
        except Exception as _e:
            print str(_e)
            if not forcing_ok:
                # normally we need to generate a new random seed, but here don't have out loop, so we just break
                break
            # execution won't stop on exception as there are multiple potential bugs


def solve_path_constraint(k, concolic_path_constraint, concolic_stack, path_conditions_and_vars):
    global I_vars, I_gen, I_balance, I_store
    global I_constraint
    j = k - 1
    while j >= 0 and concolic_stack[j][1]:
        j -= 1
    if j == -1:
        return 0, -1
    else:
        concolic_path_constraint[j] = Not(concolic_path_constraint[j])
        concolic_stack[j][0] = 1 - concolic_stack[j][0]
        solver.push()
        for i in range(j+1):
            solver.add(concolic_path_constraint[i])
        for c in I_constraint:
            solver.add(c)
        if solver.check() == sat:
            m = solver.model()
            for d in m.decls():
                name = d.name()
                if name in I_vars:
                    match_d = I_vars
                elif name in I_gen:
                    match_d = I_gen
                elif name in I_balance:
                    match_d = I_balance
                elif name in I_store:
                    match_d = I_store
                else:
                    raise KeyError('Got a variable not in I')
                match_d[name] = m[d].as_long()
            solver.pop()
            return 1, concolic_stack[0:j+1]
        else:
            solver.pop()
            return solve_path_constraint(j, concolic_path_constraint, concolic_stack, path_conditions_and_vars)


def compare_and_update_stack(branch, k, stack):
    global forcing_ok
    if k < len(stack):
        if stack[k][0] != branch:
            forcing_ok = False
            raise Exception("forcing ok")
        elif k == len(stack) - 1:
            stack[k][1] = 1
    else:
        stack.append([branch, 0])


def instrumented_program(concolic_stack):
    global gen
    # executing, starting from beginning

    stack = []
    stack_concrete = []

    mem = {}
    mem_concrete = {}

    gen = Generator()

    concolic_path_constraint = []

    visited = []

    path_conditions_and_vars = {"path_condition": []}

    global I_constraint
    I_constraint = []  # I_constraint delays init until the actual variable is created

    # this is init global state for this particular execution
    global_state, global_state_concrete = get_init_global_state(path_conditions_and_vars)
    analysis = init_analysis()
    l = 0
    k = 0

    while True:
        if_continue, l, k = sym_exec_block(
            l, visited,
            stack, stack_concrete,
            mem, mem_concrete,
            global_state, global_state_concrete,
            path_conditions_and_vars,
            analysis,
            k, concolic_path_constraint, concolic_stack)
        if not if_continue:
            break

    return solve_path_constraint(k, concolic_path_constraint, concolic_stack, path_conditions_and_vars)


def sym_add(first, second):
    if isinstance(first, (int, long)) and isinstance(second, (int, long)):
        return conc_add(first, second)
    if isinstance(first, (int, long)):
        first = BitVecVal(first, 256)
    if isinstance(second, (int, long)):
        second = BitVecVal(second, 256)
    return first + second


def sym_minus(first, second):
    if isinstance(first, (int, long)) and isinstance(second, (int, long)):
        return conc_minus(first, second)
    if isinstance(first, (int, long)):
        first = BitVecVal(first, 256)
    if isinstance(second, (int, long)):
        second = BitVecVal(second, 256)
    return first - second


def sym_times(first, second):
    if isinstance(first, (int, long)) and isinstance(second, (int, long)):
        return conc_times(first, second)
    if isinstance(first, (int, long)):
        first = BitVecVal(first, 256)
    if isinstance(second, (int, long)):
        second = BitVecVal(second, 256)
    return first * second


def sym_divide(first, second):
    if isinstance(first, (int, long)) and isinstance(second, (int, long)):
        return conc_divide(first, second)
    if isinstance(first, (int, long)):
        first = BitVecVal(first, 256)
    if isinstance(second, (int, long)):
        second = BitVecVal(second, 256)
    return first / second


def conc_add(first, second):
    return (first+second) % (2**256)


def conc_minus(first, second):
    return (first-second) % (2**256)


def conc_times(first, second):
    return (first*second) % (2**256)


def conc_divide(first, second):
    if second == 0:
        return (-1) % (2**256)
    else:
        return first / second


def conc_power(first, second):
    if second >= 256:
        return 0
    else:
        return (first ** second)%(2**256)


# Symbolically executing a block from the start address
def sym_exec_block(start, visited,
                   stack, stack_concrete,
                   mem, mem_concrete,
                   global_state, global_state_concrete,
                   path_conditions_and_vars,
                   analysis,
                   k, concolic_path_constraint, concolic_stack):
    if start < 0:
        if PRINT_MODE: print "ERROR: UNKNOWN JUMP ADDRESS. TERMINATING THIS PATH"
        return False, -1, k

    if PRINT_MODE: print "\nDEBUG: Reach block address %d \n" % start
    if PRINT_MODE: print "STACK: " + str(stack)

    if start in visited:
        if PRINT_MODE: print "Seeing a loop. Terminating this path ... "
        return False, -1, k

    # Execute every instruction, one at a time
    try:
        block_ins = vertices[start].get_instructions()
    except KeyError:
        if PRINT_MODE: print "This path results in an exception, possibly an invalid jump address"
        return False, -1, k
    inscnt = 0
    for instr in block_ins:
        # print """Inst: %d """ %(start+inscnt)+instr
        inscnt += 1
        try:
            sym_exec_ins(start, start + inscnt, instr,
                         stack, stack_concrete,
                         mem, mem_concrete,
                         global_state, global_state_concrete,
                         path_conditions_and_vars,
                         analysis)
        except Exception as e:
            print str(e)
            return False, -1, k

    # Mark that this basic block in the visited blocks
    visited.append(start)

    # Go to next Basic Block(s)
    if jump_type[start] == "terminal":
        if PRINT_MODE: print "TERMINATING A PATH ..."
        display_analysis(analysis)
        global total_no_of_paths
        total_no_of_paths += 1
        # global_pc.append(path_conditions_and_vars["path_condition"])
        reentrancy_all_paths.append(analysis["reentrancy_bug"])
        earlypay_all_paths.extend(analysis["earlypay_bug"])
        if analysis["money_flow"] not in money_flow_all_paths:
            money_flow_all_paths.append(analysis["money_flow"])
            path_conditions.append(path_conditions_and_vars["path_condition"])
            all_gs.append(copy_global_values(global_state))
        if DATA_FLOW:
            if analysis["sload"] not in data_flow_all_paths[0]:
                data_flow_all_paths[0].append(analysis["sload"])
            if analysis["sstore"] not in data_flow_all_paths[1]:
                data_flow_all_paths[1].append(analysis["sstore"])
        compare_stack_unit_test(stack)
        return False, -1, k
    # if PRINT_MODE: print "Path condition = " + str(path_conditions_and_vars["path_condition"])
    # raw_input("Press Enter to continue...\n")
    elif jump_type[start] == "unconditional":  # executing "JUMP"
        successor = vertices[start].get_jump_target()
        return True, successor, k
    elif jump_type[start] == "falls_to":  # just follow to the next basic block
        successor = vertices[start].get_falls_to()
        return True, successor, k
    elif jump_type[start] == "conditional":  # executing "JUMPI"

        # A choice point, we proceed with depth first search
        branch_expression_concrete = vertices[start].get_branch_expression_concrete()
        branch_expression = vertices[start].get_branch_expression()

        if PRINT_MODE: print "Branch expression: " + str(branch_expression) + " " + str(concolic_path_constraint)

        if branch_expression_concrete:
            concolic_path_constraint.append(branch_expression)
            path_conditions_and_vars["path_condition"].append(branch_expression)
            compare_and_update_stack(1, k, concolic_stack)
            left_branch = vertices[start].get_jump_target()
            return True, left_branch, k+1
        else:
            concolic_path_constraint.append(Not(branch_expression))
            path_conditions_and_vars["path_condition"].append(Not(branch_expression))
            compare_and_update_stack(0, k, concolic_stack)
            right_branch = vertices[start].get_falls_to()
            return True, right_branch, k+1
    else:
            print 'Unknown Jump-Type'
            return False, -1, k


# Symbolically executing an instruction
def sym_exec_ins(start, cur, instr,
                 stack, stack_concrete,
                 mem, mem_concrete,
                 global_state, global_state_concrete,
                 path_conditions_and_vars,
                 analysis):
    global all_linear, all_locs_definite
    global I_gen, I_vars, I_balance, I_constraint, I_store
    # print("""step %d""", instr)
    instr_parts = str.split(instr, ' ')

    # collecting the analysis result by calling this skeletal function
    # this should be done before symbolically executing the instruction,
    # since SE will modify the stack and mem
    update_analysis(analysis, instr_parts[0], stack, mem, global_state, path_conditions_and_vars, cur)

    if PRINT_MODE: print "=============================="
    if PRINT_MODE: print "EXECUTING: " + instr

    #
    #  0s: Stop and Arithmetic Operations
    #
    if instr_parts[0] == "STOP":
        return
    elif instr_parts[0] == "ADD":
        if len(stack) > 1:
            first = stack.pop(0)
            first_concrete = stack_concrete.pop(0)
            second = stack.pop(0)
            second_concrete = stack_concrete.pop(0)
            computed = sym_add(first, second)
            computed_concrete = conc_add(first_concrete, second_concrete)
            stack.insert(0, computed)
            stack_concrete.insert(0, computed_concrete)
        else:
            raise ValueError('STACK underflow')
    elif instr_parts[0] == "MUL":
        if len(stack) > 1:
            first = stack.pop(0)
            first_concrete = stack_concrete.pop(0)
            second = stack.pop(0)
            second_concrete = stack_concrete.pop(0)
            computed = sym_times(first, second)
            computed_concrete = conc_times(first_concrete, second_concrete)
            stack.insert(0, computed)
            stack_concrete.insert(0, computed_concrete)
        else:
            raise ValueError('STACK underflow')
    elif instr_parts[0] == "SUB":
        if len(stack) > 1:
            first = stack.pop(0)
            first_concrete = stack_concrete.pop(0)
            second = stack.pop(0)
            second_concrete = stack_concrete.pop(0)
            computed = sym_minus(first, second)
            computed_concrete = conc_minus(first_concrete, second_concrete)
            stack.insert(0, computed)
            stack_concrete.insert(0, computed_concrete)
        else:
            raise ValueError('STACK underflow')
    elif instr_parts[0] == "DIV":
        if len(stack) > 1:
            first = stack.pop(0)
            first_concrete = stack_concrete.pop(0)
            second = stack.pop(0)
            second_concrete = stack_concrete.pop(0)
            computed = sym_divide(first, second)
            computed_concrete = conc_divide(first_concrete, second_concrete)
            stack.insert(0, computed)
            stack_concrete.insert(0, computed_concrete)
        else:
            raise ValueError('STACK underflow')
    elif instr_parts[0] == "MOD":
        if len(stack) > 1:
            first = stack.pop(0)
            first_concrete = stack_concrete.pop(0)
            second = stack.pop(0)
            second_concrete = stack_concrete.pop(0)

            if second_concrete == 0:
                computed = 0
                computed_concrete = 0
            else:
                computed = first % second
                computed_concrete = first_concrete % second_concrete
            stack.insert(0, computed)
            stack_concrete.insert(0, computed_concrete)
        else:
            raise ValueError('STACK underflow')
    elif instr_parts[0] == "SMOD":
        if len(stack) > 1:
            first = stack.pop(0)
            first_concrete = stack_concrete.pop(0)
            second = stack.pop(0)
            second_concrete = stack_concrete.pop(0)

            if second_concrete == 0:
                computed = 0
                computed_concrete = 0
            else:
                computed = first % second
                computed_concrete = first_concrete % second_concrete
            stack.insert(0, computed)
            stack_concrete.insert(0, computed_concrete)
        else:
            raise ValueError('STACK underflow')
    elif instr_parts[0] == "ADDMOD":
        if len(stack) > 2:
            first = stack.pop(0)
            first_concrete = stack_concrete.pop(0)
            second = stack.pop(0)
            second_concrete = stack_concrete.pop(0)
            third = stack.pop(0)
            third_concrete = stack_concrete.pop(0)
            if third_concrete == 0:
                computed = 0
                computed_concrete = 0
            else:
                # there is one guy that is a symbolic expression
                computed = sym_add(first, second) % third
                computed_concrete = conc_add(first_concrete, second_concrete) % third_concrete
            stack.insert(0, computed)
            stack_concrete.insert(0, computed_concrete)
        else:
            raise ValueError('STACK underflow')
    elif instr_parts[0] == "MULMOD":
        if len(stack) > 2:
            first = stack.pop(0)
            first_concrete = stack_concrete.pop(0)
            second = stack.pop(0)
            second_concrete = stack_concrete.pop(0)
            third = stack.pop(0)
            third_concrete = stack_concrete.pop(0)
            if third_concrete == 0:
                computed = 0
                computed_concrete = 0
            else:
                # there is one guy that is a symbolic expression
                if isinstance(third, (int, long)):
                    third = BitVecVal(third, 256)
                computed = sym_times(first, second) % third
                computed_concrete = conc_add(first_concrete, second_concrete) % third_concrete
            stack.insert(0, computed)
            stack_concrete.insert(0, computed_concrete)
        else:
            raise ValueError('STACK underflow')
    elif instr_parts[0] == "EXP":
        if len(stack) > 1:
            stack.pop(0)
            stack.pop(0)
            base_concrete = stack_concrete.pop(0)
            exponent_concrete = stack_concrete.pop(0)
            computed = conc_power(base_concrete, exponent_concrete)
            stack.insert(0, computed)
            stack_concrete.insert(0, computed)
            all_linear = False
        else:
            raise ValueError('STACK underflow')
    elif instr_parts[0] == "SIGNEXTEND":
        if len(stack) > 1:
            _ = stack.pop(0)
            _ = stack.pop(0)
            index_concrete = stack_concrete.pop(0)
            content_concrete = stack_concrete.pop(0)
            if index_concrete > 31:
                raise ValueError('Index concrete should < 32')
            msb = 2**(8+8*index_concrete)
            content_concrete = (2**msb-1) & content_concrete
            mask = (2**msb) >> 1
            if mask & instr:
                content_concrete += (2**256 >> msb) << msb
            stack.insert(0, content_concrete)
            stack_concrete.insert(0, content_concrete)
            all_linear = False
        else:
            raise ValueError('STACK underflow')
    #
    #  10s: Comparison and Bitwise Logic Operations
    #
    elif instr_parts[0] == "LT":
        if len(stack) > 1:
            first = stack.pop(0)
            first_concrete = stack_concrete.pop(0)
            second = stack.pop(0)
            second_concrete = stack_concrete.pop(0)
            if isinstance(first, (int, long)) and isinstance(second, (int, long)):
                if first < second:
                    stack.insert(0, 1)
                    stack_concrete.insert(0, 1)
                else:
                    stack.insert(0, 0)
                    stack_concrete.insert(0, 0)
            else:
                sym_expression = If(ULT(first, second), BitVecVal(1, 256), BitVecVal(0, 256))
                stack.insert(0, sym_expression)
                sym_expression_concrete = 1 if first_concrete < second_concrete else 0
                stack_concrete.insert(0, sym_expression_concrete)
        else:
            raise ValueError('STACK underflow')
    elif instr_parts[0] == "GT":
        if len(stack) > 1:
            first = stack.pop(0)
            first_concrete = stack_concrete.pop(0)
            second = stack.pop(0)
            second_concrete = stack_concrete.pop(0)
            if isinstance(first, (int, long)) and isinstance(second, (int, long)):
                if first > second:
                    stack.insert(0, 1)
                    stack_concrete.insert(0, 1)
                else:
                    stack.insert(0, 0)
                    stack_concrete.insert(0, 0)
            else:
                sym_expression = If(UGT(first, second), BitVecVal(1, 256), BitVecVal(0, 256))
                stack.insert(0, sym_expression)
                sym_expression_concrete = 1 if first_concrete > second_concrete else 0
                stack_concrete.insert(0, sym_expression_concrete)
        else:
            raise ValueError('STACK underflow')
    elif instr_parts[0] == "SLT":  # Not fully faithful to signed comparison
        if len(stack) > 1:
            first = stack.pop(0)
            first_concrete = stack_concrete.pop(0)
            second = stack.pop(0)
            second_concrete = stack_concrete.pop(0)
            if isinstance(first, (int, long)) and isinstance(second, (int, long)):
                if first < second:
                    stack.insert(0, 1)
                    stack_concrete.insert(0, 1)
                else:
                    stack.insert(0, 0)
                    stack_concrete.insert(0, 0)
            else:
                sym_expression = If(first < second, BitVecVal(1, 256), BitVecVal(0, 256))
                stack.insert(0, sym_expression)
                sym_expression_concrete = 1 if first_concrete < second_concrete else 0
                stack_concrete.insert(0, sym_expression_concrete)
        else:
            raise ValueError('STACK underflow')
    elif instr_parts[0] == "SGT":  # Not fully faithful to signed comparison
        if len(stack) > 1:
            first = stack.pop(0)
            first_concrete = stack_concrete.pop(0)
            second = stack.pop(0)
            second_concrete = stack_concrete.pop(0)
            if isinstance(first, (int, long)) and isinstance(second, (int, long)):
                if first > second:
                    stack.insert(0, 1)
                    stack_concrete.insert(0, 1)
                else:
                    stack.insert(0, 0)
                    stack_concrete.insert(0, 0)
            else:
                sym_expression = If(first > second, BitVecVal(1, 256), BitVecVal(0, 256))
                stack.insert(0, sym_expression)
                sym_expression_concrete = 1 if first_concrete > second_concrete else 0
                stack_concrete.insert(0, sym_expression_concrete)
        else:
            raise ValueError('STACK underflow')
    elif instr_parts[0] == "EQ":
        if len(stack) > 1:
            first = stack.pop(0)
            first_concrete = stack_concrete.pop(0)
            second = stack.pop(0)
            second_concrete = stack_concrete.pop(0)
            if isinstance(first, (int, long)) and isinstance(second, (int, long)):
                if first == second:
                    stack.insert(0, 1)
                else:
                    stack.insert(0, 0)
            else:
                sym_expression = If(first == second, BitVecVal(1, 256), BitVecVal(0, 256))
                stack.insert(0, sym_expression)
            sym_expression_concrete = 1 if first_concrete == second_concrete else 0
            stack_concrete.insert(0, sym_expression_concrete)
        else:
            raise ValueError('STACK underflow')
    elif instr_parts[0] == "ISZERO":
        # Tricky: this instruction works on both boolean and integer,
        # when we have a symbolic expression, type error might occur
        # Currently handled by try and catch
        if len(stack) > 0:
            first = stack.pop(0)
            first_concrete = stack_concrete.pop(0)
            if isinstance(first, (int, long)):
                if first == 0:
                    stack.insert(0, 1)
                    stack_concrete.insert(0, 1)
                else:
                    stack.insert(0, 0)
                    stack_concrete.insert(0, 0)
            else:
                sym_expression = If(first == 0, BitVecVal(1, 256), BitVecVal(0, 256))
                stack.insert(0, sym_expression)
                sym_expression_concrete = 1 if first_concrete == 0 else 0
                stack_concrete.insert(0, sym_expression_concrete)
        else:
            raise ValueError('STACK underflow')
    elif instr_parts[0] == "AND":
        if len(stack) > 1:
            first = stack.pop(0)
            second = stack.pop(0)
            first_concrete = stack_concrete.pop(0)
            second_concrete = stack_concrete.pop(0)
            computed = first & second
            computed_concrete = first_concrete & second_concrete
            stack.insert(0, computed)
            stack_concrete.insert(0, computed_concrete)
        else:
            raise ValueError('STACK underflow')
    elif instr_parts[0] == "OR":
        if len(stack) > 1:
            first = stack.pop(0)
            second = stack.pop(0)
            first_concrete = stack_concrete.pop(0)
            second_concrete = stack_concrete.pop(0)
            computed = first | second
            computed_concrete = first_concrete | second_concrete
            stack.insert(0, computed)
            stack_concrete.insert(0, computed_concrete)
        else:
            raise ValueError('STACK underflow')
    elif instr_parts[0] == "XOR":
        if len(stack) > 1:
            first = stack.pop(0)
            second = stack.pop(0)
            first_concrete = stack_concrete.pop(0)
            second_concrete = stack_concrete.pop(0)
            computed = first ^ second
            computed_concrete = first_concrete ^ second_concrete
            stack.insert(0, computed)
            stack_concrete.insert(0, computed_concrete)
        else:
            raise ValueError('STACK underflow')
    elif instr_parts[0] == "NOT":
        if len(stack) > 0:
            first = stack.pop(0)
            first_concrete = stack_concrete.pop(0)
            if isinstance(first, (int, long)):
                first = BitVecVal(first, 256)
            sym_expression = (~ first)
            computed_concrete = (1 << 256) - 1 - first_concrete
            stack.insert(0, sym_expression)
            stack_concrete.insert(0, computed_concrete)
        else:
            raise ValueError('STACK underflow')
    elif instr_parts[0] == "BYTE":
        raise ValueError('BYTE is not yet handled')
    #
    # 20s: SHA3
    #
    elif instr_parts[0] == "SHA3":
        if len(stack) > 1:
            stack.pop(0)
            stack.pop(0)
            # todo: deterministic variable but not implement correctly
            a = stack_concrete.pop(0)
            b = stack_concrete.pop(0)
            res = simplify(BitVecVal(hash(a+b), 256)).as_long()
            # push into the execution a fresh symbolic variable
            stack.insert(0, res)
            stack_concrete.insert(0, res)
        else:
            raise ValueError('STACK underflow')
    #
    # 30s: Environment Information
    #
    elif instr_parts[0] == "ADDRESS":  # get address of currently executing account
        new_var_name = "Ia"
        stack.insert(0, path_conditions_and_vars[new_var_name])
        stack_concrete.insert(0, I_vars[new_var_name])
    elif instr_parts[0] == "BALANCE":
        if len(stack) > 0:
            # position is always a constant
            position = stack.pop(0)
            if not isinstance(position, (int, long)):
                all_locs_definite = False
            position_concrete = stack_concrete.pop()

            new_var_name = 'balance_'+str(position_concrete)
            if new_var_name in global_state["balance"]:
                stack.insert(0, global_state["balance"][new_var_name])
                stack_concrete.insert(0, global_state_concrete["balance"][new_var_name])
            else:
                if new_var_name not in I_balance:
                    I_balance[new_var_name] = random.randint(0, 2**256 - 1)
                if new_var_name not in path_conditions_and_vars:
                    path_conditions_and_vars[new_var_name] = BitVec(new_var_name, 256)
                global_state["balance"][new_var_name] = path_conditions_and_vars[new_var_name]
                global_state_concrete["balance"][new_var_name] = I_balance[new_var_name]
                stack.insert(0, global_state["balance"][new_var_name])
                stack_concrete.insert(0, global_state_concrete["balance"][new_var_name])
        else:
            raise ValueError('STACK underflow')
    elif instr_parts[0] == "CALLER":  # get caller address
        # that is directly responsible for this execution
        new_var_name = "Is"
        stack.insert(0, path_conditions_and_vars[new_var_name])
        stack_concrete.insert(0, I_vars[new_var_name])
    elif instr_parts[0] == "ORIGIN":  # get execution origination address
        new_var_name = "Io"
        if new_var_name not in I_vars:
            I_vars[new_var_name] = random.randint(0, 2**256 - 1)
        if new_var_name not in path_conditions_and_vars:
            path_conditions_and_vars[new_var_name] = BitVec(new_var_name, 256)
        stack.insert(0, path_conditions_and_vars[new_var_name])
        stack_concrete.insert(0, I_vars[new_var_name])
    elif instr_parts[0] == "CALLVALUE":  # get value of this transaction
        var_name = "Iv"
        stack.insert(0, path_conditions_and_vars[var_name])
        stack_concrete.insert(0, I_vars[var_name])
    elif instr_parts[0] == "CALLDATALOAD":  # from input data from environment
        if len(stack) > 0:
            # position is always a constant
            stack.pop(0)
            position = stack_concrete.pop(0)
            new_var_name = 'Id_'+str(position)
            if new_var_name not in I_gen:
                I_gen[new_var_name] = random.randint(0, 2 ** 256 - 1)  # max 1024
            if new_var_name not in path_conditions_and_vars:
                path_conditions_and_vars[new_var_name] = BitVec(new_var_name, 256)
            stack.insert(0, path_conditions_and_vars[new_var_name])
            stack_concrete.insert(0, I_gen[new_var_name])
        else:
            raise ValueError('STACK underflow')
    elif instr_parts[0] == "CALLDATASIZE":  # from input data from environment
        new_var_name = "Id_size"
        if new_var_name not in I_vars:
            I_vars[new_var_name] = random.randint(0, 1024)
        if new_var_name not in path_conditions_and_vars:
            path_conditions_and_vars[new_var_name] = BitVec(new_var_name, 256)
            I_constraint.append(path_conditions_and_vars[new_var_name] < BitVecVal(1024, 256))  # assume < 1024
        stack.insert(0, path_conditions_and_vars[new_var_name])
        stack_concrete.insert(0, I_vars[new_var_name])
    elif instr_parts[0] == "CALLDATACOPY":  # Copy input data to memory
        # Don't know how to simulate this yet
        if len(stack) > 2:
            stack.pop(0)
            stack.pop(0)
            stack.pop(0)
            stack_concrete.pop(0)
            stack_concrete.pop(0)
            stack_concrete.pop(0)
        else:
            raise ValueError('STACK underflow')
    elif instr_parts[0] == "CODECOPY":  # Copy code running in current env to memory
        # Don't know how to simulate this yet
        # Need an example to test
        if len(stack) > 2:
            stack.pop(0)
            stack.pop(0)
            stack.pop(0)
            stack_concrete.pop(0)
            stack_concrete.pop(0)
            stack_concrete.pop(0)
        else:
            raise ValueError('STACK underflow')
    elif instr_parts[0] == "GASPRICE":  # get address of currently executing account
        new_var_name = "Ip"
        if new_var_name not in I_vars:
            I_vars[new_var_name] = random.randint(0, 2**256-1)
        if new_var_name not in path_conditions_and_vars:
            path_conditions_and_vars[new_var_name] = BitVec(new_var_name, 256)
        stack.insert(0, path_conditions_and_vars[new_var_name])
        stack_concrete.insert(0, I_vars[new_var_name])
    #
    #  40s: Block Information
    #
    elif instr_parts[0] == "BLOCKHASH":  # information from block header
        if len(stack) > 0:
            stack.pop(0)
            stack_concrete.pop(0)
            new_var_name = "IH_blockhash"
            # treat as an input
            if new_var_name not in I_vars:
                I_vars[new_var_name] = random.randint(0, 2**256 - 1)
            if new_var_name not in path_conditions_and_vars:
                path_conditions_and_vars[new_var_name] = BitVec(new_var_name, 256)
            stack.insert(0, path_conditions_and_vars[new_var_name])
            stack_concrete.insert(0, I_vars[new_var_name])
        else:
            raise ValueError('STACK underflow')
    elif instr_parts[0] == "COINBASE":  # information from block header
        new_var_name = "IH_c"
        # treat as an input
        if new_var_name not in I_vars:
            I_vars[new_var_name] = random.randint(0, 2**256-1)
        if new_var_name not in path_conditions_and_vars:
            path_conditions_and_vars[new_var_name] = BitVec(new_var_name, 256)
        stack.insert(0, path_conditions_and_vars[new_var_name])
        stack_concrete.insert(0, I_vars[new_var_name])
    elif instr_parts[0] == "TIMESTAMP":  # information from block header
        new_var_name = "IH_s"
        # treat as an input
        if new_var_name not in I_vars:
            I_vars[new_var_name] = random.randint(0, 2**256-1)
        if new_var_name not in path_conditions_and_vars:
            path_conditions_and_vars[new_var_name] = BitVec(new_var_name, 256)
        stack.insert(0, path_conditions_and_vars[new_var_name])
        stack_concrete.insert(0, I_vars[new_var_name])
    elif instr_parts[0] == "NUMBER":  # information from block header
        new_var_name = "IH_i"
        # treat as an input
        if new_var_name not in I_vars:
            I_vars[new_var_name] = random.randint(0, 2**256-1)
        if new_var_name not in path_conditions_and_vars:
            path_conditions_and_vars[new_var_name] = BitVec(new_var_name, 256)
        stack.insert(0, path_conditions_and_vars[new_var_name])
        stack_concrete.insert(0, I_vars[new_var_name])
    elif instr_parts[0] == "DIFFICULTY":  # information from block header
        new_var_name = "IH_d"
        # treat as an input
        if new_var_name not in I_vars:
            I_vars[new_var_name] = random.randint(0, 2**256-1)
        if new_var_name not in path_conditions_and_vars:
            path_conditions_and_vars[new_var_name] = BitVec(new_var_name, 256)
        stack.insert(0, path_conditions_and_vars[new_var_name])
        stack_concrete.insert(0, I_vars[new_var_name])
    elif instr_parts[0] == "GASLIMIT":  # information from block header
        new_var_name = "IH_l"
        # treat as an input
        if new_var_name not in I_vars:
            I_vars[new_var_name] = random.randint(0, 2**256-1)
        if new_var_name not in path_conditions_and_vars:
            path_conditions_and_vars[new_var_name] = BitVec(new_var_name, 256)
        stack.insert(0, path_conditions_and_vars[new_var_name])
        stack_concrete.insert(0, I_vars[new_var_name])
    #
    #  50s: Stack, Memory, Storage, and Flow Information
    #
    elif instr_parts[0] == "POP":
        if len(stack) > 0:
            stack.pop(0)
            stack_concrete.pop(0)
        else:
            raise ValueError('STACK underflow')
    elif instr_parts[0] == "MLOAD":
        if len(stack) > 0:
            # concolic execution omit the case storing to a symbolic address
            address = stack.pop(0)
            if not isinstance(address, (int, long)):
                all_locs_definite = False
            address_concrete = stack_concrete.pop(0)
            current_miu_i = global_state["miu_i"]
            if address_concrete in mem:
                temp = long(ceil((address_concrete + 32) / float(32)))
                if temp > current_miu_i:
                    current_miu_i = temp
                value = mem[address_concrete]
                value_concrete = mem_concrete[address_concrete]
                stack.insert(0, value)
                stack_concrete.insert(0, value_concrete)
                if PRINT_MODE: print "temp: " + str(temp)
                if PRINT_MODE: print "current_miu_i: " + str(current_miu_i)
            else:
                # give a 0 to not store address
                stack.insert(0, 0)
                stack_concrete.insert(0, 0)
            global_state["miu_i"] = current_miu_i
        else:
            raise ValueError('STACK underflow')
    elif instr_parts[0] == "MSTORE":
        if len(stack) > 1:
            # concolic execution omit the case storing to a symbolic address
            stored_address = stack.pop(0)
            if not isinstance(stored_address, (int, long)):
                all_locs_definite = False
            stored_value = stack.pop(0)
            stored_address_concrete = stack_concrete.pop(0)
            stored_value_concrete = stack_concrete.pop(0)
            current_miu_i = global_state["miu_i"]
            temp = long(ceil((stored_address_concrete + 32) / float(32)))
            if temp > current_miu_i:
                current_miu_i = temp
            mem[stored_address_concrete] = stored_value  # note that the stored_value could be symbolic
            mem_concrete[stored_address_concrete] = stored_value_concrete  # note that the stored_value could be symbolic
            if PRINT_MODE: print "temp: " + str(temp)
            if PRINT_MODE: print "current_miu_i: " + str(current_miu_i)
            global_state["miu_i"] = current_miu_i
        else:
            raise ValueError('STACK underflow')
    elif instr_parts[0] == "MSTORE8":
        if len(stack) > 1:
            stored_address = stack.pop(0)
            if not isinstance(stored_address, (int, long)):
                all_locs_definite = False
            temp_value = stack.pop(0)
            stored_value = temp_value % 256  # get the least byte
            stored_address_concrete = stack_concrete.pop(0)
            temp_value_concrete = stack_concrete.pop(0)
            stored_value_concrete = temp_value_concrete % 256
            current_miu_i = global_state["miu_i"]
            temp = long(ceil((stored_address_concrete + 32) / float(32)))
            if temp > current_miu_i:
                current_miu_i = temp
            mem[stored_address_concrete] = stored_value  # note that the stored_value could be symbolic
            mem_concrete[stored_address_concrete] = stored_value_concrete  # note that the stored_value could be symbolic
            if PRINT_MODE: print "temp: " + str(temp)
            if PRINT_MODE: print "current_miu_i: " + str(current_miu_i)
            global_state["miu_i"] = current_miu_i
        else:
            raise ValueError('STACK underflow')
    elif instr_parts[0] == "SLOAD":
        if len(stack) > 0:
            # concolic execution omit the case storing to a symbolic address
            address = stack.pop(0)
            if not isinstance(address, (int, long)):
                all_locs_definite = False
            address_concrete = stack_concrete.pop(0)

            new_var_name = "Ia_store_"+str(address_concrete)
            if new_var_name in global_state["Ia"]:
                stack.insert(0, global_state["Ia"][new_var_name])
                stack_concrete.insert(0, global_state_concrete["Ia"][new_var_name])
            else:
                if new_var_name not in I_store:
                    I_store[new_var_name] = random.randint(0, 2 ** 256 - 1)  # max 1024
                if new_var_name not in path_conditions_and_vars:
                    path_conditions_and_vars[new_var_name] = BitVec(new_var_name, 256)
                global_state["Ia"][new_var_name] = path_conditions_and_vars[new_var_name]
                global_state_concrete["Ia"][new_var_name] = I_store[new_var_name]
                stack.insert(0, global_state["Ia"][new_var_name])
                stack_concrete.insert(0, global_state_concrete["Ia"][new_var_name])
                path_conditions_and_vars[new_var_name] = global_state["Ia"][new_var_name]
        else:
            raise ValueError('STACK underflow')
    elif instr_parts[0] == "SSTORE":
        if len(stack) > 1:
            # concolic execution omit the case storing to a symbolic address
            stored_address = stack.pop(0)
            if not isinstance(stored_address, (int, long)):
                all_locs_definite = False
            stored_value = stack.pop(0)
            stored_address_concrete = stack_concrete.pop(0)
            stored_value_concrete = stack_concrete.pop(0)
            new_var_name = "Ia_store_"+str(stored_address_concrete)
            global_state["Ia"][new_var_name] = stored_value  # note that the stored_value could be unknown
            global_state_concrete["Ia"][new_var_name] = stored_value_concrete
        else:
            raise ValueError('STACK underflow')
    elif instr_parts[0] == "JUMP":
        if len(stack) > 0:
            # address must be real
            target_address = stack.pop(0)
            if not isinstance(target_address, (int, long)):
                all_locs_definite = False
            target_address_concrete = stack_concrete.pop(0)
            vertices[start].set_jump_target(target_address_concrete)
            if target_address_concrete not in edges[start]:
                edges[start].append(target_address_concrete)
        else:
            raise ValueError('STACK underflow')
    elif instr_parts[0] == "JUMPI":
        # WE need to prepare two branches
        if len(stack) > 1:
            target_address = stack.pop(0)
            if not isinstance(target_address, (int, long)):
                all_locs_definite = False
            target_address_concrete = stack_concrete.pop(0)
            vertices[start].set_jump_target(target_address_concrete)
            b = stack_concrete.pop(0)
            c = stack.pop(0)
            vertices[start].set_branch_expression_concrete(b)
            vertices[start].set_branch_expression(c != 0)
            if target_address not in edges[start]:
                edges[start].append(target_address)
        else:
            raise ValueError('STACK underflow')
    elif instr_parts[0] == "PC":
        # this is not hard, but tedious. Let's skip it for now
        raise Exception('Must implement PC now')
    elif instr_parts[0] == "MSIZE":
        msize = conc_times(32, global_state["miu_i"])
        stack.insert(0, msize)
        stack_concrete.insert(0, msize)
    elif instr_parts[0] == "GAS":
        # In general, we do not have this precisely. It depends on both
        # the initial gas and the amount has been depleted
        # we need o think about this in the future, in case precise gas
        # can be tracked
        # concolic execution: use counter
        n = gen.gen_gas_var_concrete()
        stack.insert(0, n)
        stack_concrete.insert(0, n)
    elif instr_parts[0] == "JUMPDEST":
        # Literally do nothing
        pass
    #
    #  60s & 70s: Push Operations
    #
    elif instr_parts[0].startswith('PUSH', 0):  # this is a push instruction
        pushed_value = int(instr_parts[1], 16)
        stack.insert(0, pushed_value)
        stack_concrete.insert(0, pushed_value)
    #
    #  80s: Duplication Operations
    #
    elif instr_parts[0].startswith("DUP", 0):
        position = int(instr_parts[0][3:], 10) - 1
        if len(stack) > position:
            duplicate = stack[position]
            duplicate_concrete = stack_concrete[position]
            stack.insert(0, duplicate)
            stack_concrete.insert(0, duplicate_concrete)
        else:
            raise ValueError('STACK underflow')

    #
    #  90s: Swap Operations
    #
    elif instr_parts[0].startswith("SWAP", 0):
        position = int(instr_parts[0][4:], 10)
        if len(stack) > position:
            stack[position], stack[0] = stack[0], stack[position]
            stack_concrete[position], stack_concrete[0] = stack_concrete[0], stack_concrete[position]
        else:
            raise ValueError('STACK underflow')

    #
    #  a0s: Logging Operations
    #
    elif instr_parts[0] in ("LOG0", "LOG1", "LOG2", "LOG3", "LOG4"):
        # We do not simulate these logging operations
        num_of_pops = 2 + int(instr_parts[0][3:])
        while num_of_pops > 0:
            stack.pop(0)
            stack_concrete.pop(0)
            num_of_pops -= 1

    #
    #  f0s: System Operations
    #
    elif instr_parts[0] == "CALL":
        # DOTO: Need to handle miu_i
        if len(stack) > 6:
            outgas = stack.pop(0)
            recipient = stack.pop(0)
            transfer_amount = stack.pop(0)
            start_data_input = stack.pop(0)
            size_data_input = stack.pop(0)
            start_data_output = stack.pop(0)
            size_data_ouput = stack.pop(0)

            outgas_concrete = stack_concrete.pop(0)
            recipient_concrete = stack_concrete.pop(0)
            transfer_amount_concrete = stack_concrete.pop(0)
            start_data_input_concrete = stack_concrete.pop(0)
            size_data_input_concrete = stack_concrete.pop(0)
            start_data_output_concrete = stack_concrete.pop(0)
            size_data_ouput_concrete = stack_concrete.pop(0)
            # in the paper, it is shaky when the size of data output is
            # min of stack[6] and the | o |

            if not isinstance(transfer_amount, (int, long)):
                all_linear = False

            if transfer_amount_concrete == 0:
                stack.insert(0, 1)  # x = 0
                stack_concrete.insert(0, 1)  # x = 0
                return

            # Let us ignore the call depth
            balance_ia = global_state["balance"]['balance_'+str(I_vars["Ia"])]
            if not isinstance(balance_ia, (int, long)):
                all_linear = False
            balance_ia_concrete = global_state_concrete["balance"]['balance_'+str(I_vars["Ia"])]
            is_enough_fund = (balance_ia < transfer_amount)  # todo: reverse error?
            is_enough_fund_concrete = (balance_ia_concrete < transfer_amount_concrete)
            if not is_enough_fund_concrete:
                # this means not enough fund, thus the execution will result in exception
                stack.insert(0, 0)  # x = 0
                stack_concrete.insert(0, 0)  # x = 0
            else:
                # todo:
                # the execution is possibly okay
                stack.insert(0, 1)  # x = 1
                stack_concrete.insert(0, 1)  # x = 1

                path_conditions_and_vars["path_condition"].append(is_enough_fund)
                new_balance_ia = (balance_ia - transfer_amount)
                new_balance_ia_concrete = (balance_ia_concrete - transfer_amount_concrete)
                global_state["balance"]['balance_'+str(I_vars["Ia"])] = new_balance_ia
                global_state_concrete["balance"]['balance_'+str(I_vars["Ia"])] = new_balance_ia_concrete
                address_is = path_conditions_and_vars["Is"]
                address_is = (address_is & CONSTANT_ONES_159)
                address_is_concrete = I_vars["Is"]
                address_is_concrete = (address_is_concrete & CONSTANT_ONES_159)

                boolean_expression = (recipient != address_is)
                boolean_expression_concrete = (recipient_concrete != address_is_concrete)
                if not boolean_expression_concrete:
                    new_balance_is = (global_state["balance"]['balance_'+str(I_vars["Is"])] + transfer_amount)
                    new_balance_is_concrete = (global_state_concrete["balance"]['balance_'+str(I_vars["Is"])]
                                               + transfer_amount_concrete)
                    global_state["balance"]['balance_'+str(I_vars["Is"])] = new_balance_is
                    global_state["balance"]['balance_'+str(I_vars["Is"])] = new_balance_is_concrete
                else:
                    new_var_name = 'balance_'+str(recipient_concrete)

                    if new_var_name not in global_state["balance"]:
                        if new_var_name not in I_balance:
                            I_balance[new_var_name] = random.randint(0, 2**256 - 1)
                        if new_var_name not in path_conditions_and_vars:
                            path_conditions_and_vars[new_var_name] = BitVec(new_var_name, 256)
                        global_state["balance"][new_var_name] = path_conditions_and_vars[new_var_name]
                        global_state_concrete["balance"][new_var_name] = I_balance[new_var_name]

                    old_balance = global_state["balance"][new_var_name]
                    old_balance_concrete = global_state_concrete["balance"][new_var_name]
                    new_balance = sym_add(old_balance, transfer_amount)
                    new_balance_concrete = conc_add(old_balance_concrete, transfer_amount_concrete)
                    global_state["balance"][new_var_name] = new_balance
                    global_state_concrete["balance"][new_var_name] = new_balance_concrete
        else:
            raise ValueError('STACK underflow')
    elif instr_parts[0] == "CALLCODE":
        # DOTO: Need to handle miu_i
        if len(stack) > 6:
            outgas = stack.pop(0)
            stack.pop(0)  # this is not used as recipient
            transfer_amount = stack.pop(0)
            start_data_input = stack.pop(0)
            size_data_input = stack.pop(0)
            start_data_output = stack.pop(0)
            size_data_ouput = stack.pop(0)

            outgas_concrete = stack_concrete.pop(0)
            stack_concrete.pop(0)
            transfer_amount_concrete = stack_concrete.pop(0)
            start_data_input_concrete = stack_concrete.pop(0)
            size_data_input_concrete = stack_concrete.pop(0)
            start_data_output_concrete = stack_concrete.pop(0)
            size_data_ouput_concrete = stack_concrete.pop(0)
            # in the paper, it is shaky when the size of data output is
            # min of stack[6] and the | o |

            if not isinstance(transfer_amount, (int, long)):
                all_linear = False

            if transfer_amount_concrete == 0:
                stack.insert(0, 1)  # x = 0
                stack_concrete.insert(0, 1)  # x = 0
                return

            # Let us ignore the call depth
            balance_ia = global_state["balance"]['balance_'+str(I_vars["Ia"])]
            if not isinstance(balance_ia, (int, long)):
                all_linear = False
            balance_ia_concrete = global_state_concrete["balance"]['balance_'+str(I_vars["Ia"])]
            is_enough_fund = (balance_ia < transfer_amount)  # todo: reverse error?
            is_enough_fund_concrete = (balance_ia_concrete < transfer_amount_concrete)

            if not is_enough_fund_concrete:
                # this means not enough fund, thus the execution will result in exception
                stack.insert(0, 0)  # x = 0
                stack_concrete.insert(0, 0)  # x = 0
            else:
                # the execution is possibly okay
                stack.insert(0, 1)  # x = 1
                stack_concrete.insert(0, 1)  # x = 1

                path_conditions_and_vars["path_condition"].append(is_enough_fund)
        else:
            raise ValueError('STACK underflow')
    elif instr_parts[0] == "RETURN":
        # DOTO: Need to handle miu_i
        if len(stack) > 1:
            stack.pop(0)
            stack.pop(0)
            stack_concrete.pop(0)
            stack_concrete.pop(0)
            # TODO
            pass
        else:
            raise ValueError('STACK underflow')
    elif instr_parts[0] == "SUICIDE":
        recipient = stack.pop(0)
        recipient_concrete = stack.pop(0)
        transfer_amount = global_state["balance"]['balance_'+str(I_vars["Ia"])]
        transfer_amount_concrete = global_state_concrete["balance"]['balance_'+str(I_vars["Ia"])]
        global_state["balance"]['balance_'+str(I_vars["Ia"])] = 0
        global_state_concrete["balance"]['balance_'+str(I_vars["Ia"])] = 0

        new_var_name = 'balance_'+str(recipient_concrete)

        if new_var_name not in global_state["balance"]:
            if new_var_name not in I_balance:
                I_balance[new_var_name] = random.randint(0, 2**256 - 1)
            if new_var_name not in path_conditions_and_vars:
                path_conditions_and_vars[new_var_name] = BitVec(new_var_name, 256)
            global_state["balance"][new_var_name] = path_conditions_and_vars[new_var_name]
            global_state_concrete["balance"][new_var_name] = I_balance[new_var_name]

        old_balance = global_state["balance"][new_var_name]
        old_balance_concrete = global_state_concrete["balance"][new_var_name]
        new_balance = sym_add(old_balance, transfer_amount)
        new_balance_concrete = conc_add(old_balance_concrete, transfer_amount_concrete)
        global_state["balance"][new_var_name] = new_balance
        global_state_concrete["balance"][new_var_name] = new_balance_concrete
        # TODO
        return

    else:
        if PRINT_MODE: print "UNKNOWN INSTRUCTION: " + instr_parts[0]
        raise Exception('UNKNOWN INSTRUCTION' + instr_parts[0])

    print_state(start, stack, mem, global_state)


def check_callstack_attack(disasm):
    problematic_instructions = ['CALL', 'CALLCODE']
    for i in xrange(0, len(disasm)):
        instruction = disasm[i]
        if instruction[1] in problematic_instructions:
            error = True
            for j in xrange(i + 1, len(disasm)):
                if disasm[j][1] in problematic_instructions:
                    break
                if disasm[j][1] == 'ISZERO':
                    error = False
                    break
            if error == True: return True
    return False


def run_callstack_attack():
    disasm_data = open(sys.argv[1]).read()
    instr_pattern = r"([\d]+) +([A-Z]+)([\d]?){1}(?: +(?:=> )?(\d+)?)?"
    instructions = re.findall(instr_pattern, disasm_data)

    result = check_callstack_attack(instructions)

    print "\t  CallStack Attack: \t %s" % result

    results['callstack'] = result


def run_early_pay_attack():
    tmp = sorted(set(earlypay_all_paths))
    if (len(tmp) > 0):
        print "\t  EarlyPay Warning Founded in: " + str(tmp)
    else:
        print "\t  EarlyPay Warning:\t False"


def print_state(block_address, stack, mem, global_state):
    if PRINT_MODE: print "STACK: " + str(stack)
    if PRINT_MODE: print "MEM: " + str(mem)
    if PRINT_MODE: print "GLOBAL STATE: " + str(global_state)


if __name__ == '__main__':
    main()
