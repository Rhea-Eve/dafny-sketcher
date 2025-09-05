import re
from typing import List, Optional
from llm import default_generate as generate
import sketcher

def drive_ex(ex):
    p = None
    while p is None:
        p = spec_maker(ex)
    print("SPEC")
    print(p)
    return drive_program(p)

def drive_program(p: str, max_iterations: Optional[int] = None) -> str:
    i = 0
    while max_iterations is None or i < max_iterations:
        i += 1
        todo = sketcher.sketch_next_todo(p)
        done = sketcher.sketch_done(p)
        if todo is None:
            return p
        xp = dispatch_implementer(p, todo, done)
        if xp is None:
            print("Didn't solve todo")
            continue
        p = xp
        print("PROGRAM")
        print(p)
    print(f'Solved in {i} iterations')
    return p

def spec_maker(idea: str) -> str:
    prompt = prompt_spec_maker(idea)
    r = generate(prompt)
    p = extract_dafny_program(r)
    if p is None:
        print("Missing Dafny program")
        return None
    e = sketcher.show_errors(p)
    if e is not None:
        print("Errors in spec maker:", e)
        return None
    return p

#dispatch_implementer is called by the MCTS logic (from child_finder) 
# whenever the tree decides it wants to “work on” a todo item in the program.
def dispatch_implementer(p: str, todo, done) -> str:
    # Print the current TODO and its type
    print("=== LLM Implementer Called ===")
    print("TODO:", todo)
    print("Type:", todo.get('type'))

    if todo['type'] == 'function':
        return llm_implementer(p, todo)
    elif todo['type'] == 'lemma':
        return lemma_implementer(p, todo, done)

def lemma_implementer(p: str, todo, done) -> str:
    xp = implementer(p, "", todo)
    if xp:
        print("Empty proof works!")
        return xp
    x = sketcher.sketch_induction(insert_program_todo(todo, p, ""), todo['name'])
    xp = implementer(p, x, todo)
    if xp:
        print("Induction sketcher works!")
        return xp
    ip = insert_program_todo(todo, p, "")
    cs = sketcher.sketch_counterexamples(ip, todo['name'])
    if cs:
        cs_str = "\n".join(cs)
        # TODO: could force the edit further
        return llm_implementer(p, todo, done=done, hint="We found the following counterexamples to the lemma:\n" + cs_str+ "\nConsider editing the code instead of continuing to prove an impossible lemma.", edit_hint="A previous attempt had the following counterexamples for a desired property -- consider these carefully:\n" + cs_str)
    return llm_implementer(p, todo, done=done, hint="This induction sketch did NOT work on its own, but could be a good starting point if you vary/augment it:\n" + x)




def llm_implementer(
    p: str,
    todo,
    prev: str = None,
    hint: str = None,
    done: list[object] = None,
    edit_hint: str = None
) -> str:
    """
    Generates or edits a function or lemma in Dafny using LLM with explicit framing.

    The prompt structure:
    1. Framing instructions: only Dafny code, wrap in // BEGIN DAFNY ... // END DAFNY
    2. Current program
    3. Hints (from induction sketches, counterexamples, or previous hints)
    4. Previous attempts and their errors
    5. Optional edit instructions for reimplementing prior functions
    """

    # 1. General framing
    framing = (
        "You are an expert Dafny programmer.\n"
        "Your goal is to implement code in the given Dafny program.\n"
        "Focus only on the item named '{name}'.\n"
        "Only output valid Dafny code between the markers exactly as shown:\n"
        "// BEGIN DAFNY\n"
        "<your code here>\n"
        "// END DAFNY\n"
        "Do not add any explanation or commentary outside the markers.\n\n"
    )

    # 2. Function- or lemma-specific framing
    function_framing = (
        "Task: Implement the body of a Dafny function that is specified but not yet implemented.\n"
        "Function to implement: {name}\n\n"
        "Requirements:\n"
        "- Only output the body of the function (no outer braces).\n"
        "- Begin with the line `// BEGIN DAFNY` and end with the line `// END DAFNY`.\n"
        "- Do not include explanations or comments outside these markers.\n\n"
        "Reference: Dafny syntax reminders\n"
        "- Pattern matching:\n"
        "    match e\n"
        "    case Case1(arg1, arg2) => result1\n"
        "    case Case2(arg1) => result2\n"
        "    case _ => result3\n\n"
        "- Use braces for multi-statement results (e.g., with variable assignments).\n"
        "- Nested matches must be wrapped in parentheses:\n"
        "    match e1\n"
        "    case Case1(e2, _) =>\n"
        "        (match e2\n"
        "         case Case2(c2) => result2)\n"
        "    case _ => result3\n\n"
        "- Variable assignment:\n"
        "    var x := e;\n"
        "  (Semicolons are only needed for assignments.)\n"
    )

    lemma_framing = (
        "Task: Implement the body of a Dafny lemma that is specified but not yet proven.\n"
        "Lemma to implement: {name}\n\n"
        "Requirements:\n"
        "- Only output the body of the lemma (no outer braces).\n"
        "- Begin with the line `// BEGIN DAFNY` and end with the line `// END DAFNY`.\n"
        "- Do not include explanations or comments outside these markers.\n"
    )

    # Fill in program and name
    ttype = todo.get('type', 'item')
    tname = todo.get('name', '<unknown>')

    if ttype == 'function':
        specific_framing = function_framing.format(program=p, name=tname)
    else:
        specific_framing = lemma_framing.format(program=p, name=tname)

    # 3. Build the structured prompt
    prompt_parts = []
    prompt_parts.append(framing.format(name=tname))
    prompt_parts.append(specific_framing)
    prompt_parts.append(f"### Task:\nImplement or fix the {ttype} '{tname}'.\n\n")

    # 4. Hints
    if hint:
        prompt_parts.append("### Hints:\n")
        prompt_parts.append(hint + "\n\n")

    # 5. Previous attempts/errors
    if prev:
        prompt_parts.append("### Previous attempts and errors:\n")
        prompt_parts.append(prev + "\n\n")

    # 6. Optional edit instructions
    done_functions = [u['name'] for u in done if u.get('type') == 'function'] if done else []
    if done_functions:
        prompt_parts.append(
            "### Optional edits:\n"
            f"If you think it's impossible to implement {tname} without re-implementing one of the previous functions, "
            "you can write in one line:\n"
            "// EDIT <function name>\n"
            "where <function name> is one of the following: "
            + ", ".join(done_functions) + "\n\n"
        )

    prompt = "".join(prompt_parts)

    # Debug
    print("=== PROMPT SENT TO LLM ===")
    print(prompt)

    # Call LLM
    r = generate(prompt)
    print("=== LLM RESPONSE ===")
    print(r)

    # Handle EDIT
    edit_function = extract_edit_function(r, done_functions)
    if edit_function:
        return llm_edit_function(p, todo, done, edit_function, hint=edit_hint)

    # Extract Dafny code
    x = extract_dafny_program(r)
    if x is not None:
        x = extract_dafny_body(x, todo)
    if x is None:
        print("Missing Dafny program")
        return None

    # Insert back
    xp = insert_program_todo(todo, p, x)
    if xp is None:
        print("Couldn't patch program")
        return None

    # Verify
    e = sketcher.show_errors(xp)
    if e is not None:
        print("Errors in implementer:", e)
        if prev is None:
            return llm_implementer(p, todo, prev=e, hint=hint, done=done, edit_hint=edit_hint)
        return None

    return xp



'''

def llm_implementer(p: str, todo, prev: str = None, hint: str = None, done: list[object] = None, edit_hint: str = None) -> str:
    """
    Generates or edits a function or lemma in Dafny using LLM with explicit framing.

    The prompt structure:
    1. Framing instructions: only Dafny code, wrap in // BEGIN DAFNY ... // END DAFNY
    2. Current program
    3. Hints (from induction sketches, counterexamples, or previous hints)
    4. Previous attempts and their errors
    5. Optional edit instructions for reimplementing prior functions
    """

    # Basic framing: require only Dafny code between markers

    #FIX
    framing = (
        "You are an expert Dafny programmer.\n"
        You are an expert Dafny programmer. Your goal is to implement functions in the given Dafny program.
        Focus only on the function named '{name}
        "Only output valid Dafny code between the markers exactly as shown:\n"
        "// BEGIN DAFNY\n"
        "<your code here>\n"
        "// END DAFNY\n"
        "Do not add any explanation or commentary outside the markers.\n\n"
    )

    function_framing = "_____"

    lemma_framing = "def prompt_lemma_implementer(program: str, name: str) -> str:
    return f"You are implementing a lemma in a Dafny program that is specified but not fully implemented. The current program is\n{program}\n\nThe lemma to implement is {name}. Please just provide the body of the lemma (without the outer braces), starting with a line \"// BEGIN DAFNY\", ending with a line \"// END DAFNY\"."

    prompt = framing + if todo['type'] == 'function' then function_framing  else lemma_framing

    if hint is not None:
        prompt += "\n" + hint

    

    # Current program context
    prompt = framing
    prompt += "### Current Dafny program:\n"
    prompt += p + "\n\n"

    # Task description (function or lemma)
    ttype = todo.get('type', 'item')
    tname = todo.get('name', '<unknown>')
    prompt += f"### Task:\nImplement or fix the {ttype} '{tname}'. Provide only the body (no outer braces) if implementing a function/lemma body.\n\n"



    prompt = prompt_function_implementer(p, todo['name']) if todo['type'] == 'function' else prompt_lemma_implementer(p, todo['name'])
    if hint is not None:
        prompt += "\n" + hint

    #to do add the preivous code
    if prev is not None:
        prompt += f"\nFYI only, a previous attempt on this {todo['type']} had the following errors:\n{prev}"
    done_functions = [u['name'] for u in done if u['type'] == 'function'] if done else []

    if done_functions:
        prompt += f"\nIf you think it's impossible to implement {todo['name']} without re-implementing one of the previous functions, you can write in one line\n// EDIT <function name>\n where <function name> is one of the following: " + ", ".join(done_functions) + f" to ask to re-implement the function instead of implementing {todo['name']}."
    print(prompt)
    r = generate(prompt)

    print(r)
    edit_function = extract_edit_function(r, done_functions)
    if edit_function is not None:
        return llm_edit_function(p, todo, done, edit_function, hint=edit_hint)
    x = extract_dafny_program(r)
    if x is not None:
        x = extract_dafny_body(x, todo)
    if x is None:
        print("Missing Dafny program")
        return None
    xp = insert_program_todo(todo, p, x)
    if xp is None:
        print("Couldn't patch program")
        return None
    e = sketcher.show_errors(xp)
    if e is not None:
        print("Errors in implementer:", e)
        if prev is None:
            return llm_implementer(p, todo, e)
        return None
    return xp
'''
    

def llm_edit_function(p: str, todo, done, edit_function, hint: str = None) -> str:
    print('EDIT', edit_function)
    edit_todo = [u for u in done if u['name'] == edit_function][0]
    xp = llm_implementer(p, edit_todo, hint=f"You chose to re-implement {edit_function} instead of implementing {todo['name']}." + " "+hint if hint else "")
    if xp is None or xp == p:
        return erase_implementation(p, edit_todo)
    return xp

def remove_think_blocks(text):
    return re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL)

def extract_edit_function(text: str, functions: List[str]) -> Optional[str]:
    pattern = re.compile(r'^\s*// EDIT\s+(\w+)', re.MULTILINE)
    matches = pattern.findall(text)
    results = [fn for fn in matches if fn in functions]
    return results[0] if results else None

def extract_dafny_program(text: str) -> str:
    """Extract the Dafny program between the markers."""
    text = remove_think_blocks(text)
    start_marker = '// BEGIN DAFNY'
    end_marker = '// END DAFNY'
    start_idx = text.find(start_marker)
    end_idx = text.find(end_marker)
    if start_idx == -1 or end_idx == -1:
        return None
    return text[start_idx + len(start_marker):end_idx].strip()

def extract_dafny_body(x: str, todo) -> str:
    if todo['type'] in x:
        start = x.find('{')
        if start == -1:
            sign = todo['insertLine'] - todo['startLine'] + 1
            lines = x.split('\n')
            return '\n'.join(lines[sign:])
        else:
            return x[x.index('{')+1:x.rindex('}')-1]
    return x

def implementer(p: str, x: str, todo) -> str:
    if x is None:
        print("Missing Dafny program")
        return None
    xp = insert_program_todo(todo, p, x)
    if xp is None:
        print("Couldn't patch program")
        return None
    e = sketcher.show_errors(xp)
    if e is not None:
        print("Errors in implementer:", e)
        return None
    return xp

def line_col_to_offset(lines: list[str], line: int, col: int) -> int:
    return sum(len(l) for l in lines[:line - 1]) + (col - 1)

def line_col_to_start_offset(p: str,lines: list[str], line: int, col: int) -> int:
    return line_col_to_offset(lines, line, col)

def line_col_to_end_offset(p: str, lines: list[str], line: int, col: int) -> int:
    return line_col_to_offset(lines, line, col)+1

def erase_implementation(p: str, todo) -> str:
    assert todo['type'] == 'function'
    lines = p.splitlines(keepends=True)
    start_offset = line_col_to_start_offset(p, lines, todo['insertLine'], todo['insertColumn'])
    end_offset = line_col_to_end_offset(p, lines, todo['endLine'], todo['endColumn'])
    xp = p[:start_offset] + p[end_offset:]
    print("ERASE")
    print("from", start_offset, "to", end_offset)
    print(xp)
    return xp

def insert_program_todo(todo, p, x):
    if todo['status'] != 'todo':
        lines = p.splitlines(keepends=True)
        start_offset = line_col_to_start_offset(p,lines, todo['insertLine'], todo['insertColumn'])
        end_offset = line_col_to_end_offset(p, lines, todo['endLine'], todo['endColumn'])
        xp = p[:start_offset] + "{\n" + x + "\n}" + p[end_offset:]
    else:
        line = todo['insertLine']
        lines = p.split('\n')
        lines[line-1] = lines[line-1] + "\n{\n" + x + "\n}\n"
        if todo['type'] == 'lemma':
            line_lemma = todo['startLine']
            lines[line_lemma-1] = lines[line_lemma-1].replace('{:axiom}', '')
        xp = '\n'.join(lines)
    print("XP")
    print(xp)
    return xp

def prompt_spec_maker(idea: str) -> str:
    return f"You are translating an idea for a Dafny program into a specification, consisting of datatypes, function signatures (without implementation bodies) and lemmas (for lemmas only, using the {{:axiom}} attribute after lemma keyword and without body). Here is the idea:\n{idea}\n\nPlease output the specification without using an explicit module. Omit the bodies for functions and lemmas -- Do not even include the outer braces.  Please keep a comment before each function to explain what it should do. Provide the program spec, starting with a line \"// BEGIN DAFNY\", ending with a line \"// END DAFNY\"." + """\n
General hints about Dafny:
Do not generally use semicolons at the end of lines.
The attribute {:axiom} comes after the lemma keyword, and should not be used for functions. Example:
lemma {:axiom} lemma_zero_neutral(i: int)
ensures i + 0 == i
"""

def prompt_function_implementer(program: str, name: str) -> str:
    return f"You are implementing a function in a Dafny program that is specified but not fully implemented. The current program is\n{program}\n\nThe function to implement is {name}. Please just provide the body of the function (without the outer braces), starting with a line \"// BEGIN DAFNY\", ending with a line \"// END DAFNY\".\nSome hints about Dafny:\n" + """
The syntax for pattern match in Dafny is
match e
case Case1(arg1, arg2) => result1
case Case2(arg1) => result2
case _ => result3
You'll also need to have braces surrounding a result if is made of complex statements such as variable assignments.
For nested pattern matches, put the nested pattern match in parentheses:
match e1
case Case1(e2, _) =>
  (match e2
   case Case2(c2) => result 2
  )
case _ => result3

The syntax for variable assignment is
var x := e;

Variable assignments is one of the rare cases where semicolons are needed.
Only use semicolons at the end of lines where you are assigning a variable.
"""

def prompt_lemma_implementer(program: str, name: str) -> str:
    return f"You are implementing a lemma in a Dafny program that is specified but not fully implemented. The current program is\n{program}\n\nThe lemma to implement is {name}. Please just provide the body of the lemma (without the outer braces), starting with a line \"// BEGIN DAFNY\", ending with a line \"// END DAFNY\"."

if __name__ == "__main__":
    import tests
    tests.run(drive_program)
    if False:
        print('GIVEN IDEA')
        result = drive_ex(tests.idea)
        print("FINAL RESULT GIVEN IDEA")
        print(result)
