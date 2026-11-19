# src/engine/workflow_creation.py
import os

import ollama
import yaml

from agent import BY_NAME
from workflow import validate

WORKFLOWS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "workflows")

SPEC = """You write workflow YAML for an agent orchestrator. Return raw YAML only, no fence, no commentary.

Goal: "{goal}"

name: snake_case_name
purpose: one sentence
alwaysOn: true or false     # true keeps the workflow cycling forever
interval: 300               # seconds between cycles, only matters when alwaysOn
schedule: "*/15 * * * *"    # five cron fields, instead of alwaysOn, for a fixed timetable
compute:                    # hold a cycle until the machine is quiet enough. Use for heavy models
  max_cpu: 70               # percent of all cores
  min_free_ram_gb: 8
  max_gpu: 60               # percent
  min_free_gpu_gb: 4
safeguards:                 # everything below is OFF unless the goal truly needs it
  allow_shell: false        # run_shell_command refuses until this is true
  allow_email: false        # send_email refuses until this is true
  allow_private_network: false   # web tools refuse localhost and internal addresses until this is true
  allow_paths: []           # extra folders the file tools may touch. Files default to the workflow folder
nodes:                      # run top to bottom, each node's output becomes the next node's input
  - type: input | agent | output
    name: unique_snake_case
    mode: sync | async      # default sync. async runs in its own thread and keeps producing

input node, pick one source:
    source: text    value: "the concrete task, stated in full"
    source: file    path: /absolute/path
    source: api     url: https://...   method: GET   headers: {{}}   body: {{}}
    source: mcp     url: https://...   tool: tool_name   arguments: {{}}

agent node:
    model: must be one of these installed models: {models}
    system_prompt: blunt order, under 25 words, no greetings, no disclaimers
    tools: [names from the tool list below, grant only what this agent needs]
    require_tools: [the ones it must actually call]
                            # the engine makes it call these before it may answer, and fails the node if it
                            # refuses. Use it for every fact the agent is not allowed to invent
    schema:                 # a JSON Schema object, nested under THIS node, forces the answer's shape
      type: object
      properties: {{...}}
    interval: 600           # seconds between its own runs, only with mode: async

    when: not_empty | has_records | contains:word | missing:word | matches:regex
                            # skip this node unless the condition holds for what reached it
    retry: 2                # try again on failure, backing off
    on_error: stop | continue
    map: true               # agent only: run once per incoming record, side by side
    parallel: 4             # how many at a time when map is on
    mcp:                    # agent only: hand it every tool an MCP server offers
      - url: https://server/mcp

approval node: type: approval, name, prompt: "Send it?" — holds the chain until a person agrees
workflow node: type: workflow, name, ref: another_workflow_folder — runs that workflow and passes its result on

output node:
    wait: 120               # seconds to wait for async results, optional
    dedupe: link            # never report a record whose link was already reported
    sink: print | file | csv | sqlite | webhook | slack
    path: results.csv       # for file, csv and sqlite, written inside the workflow folder
    url: ${{env:SLACK_WEBHOOK}}   # for webhook and slack. Secrets go in ${{env:NAME}}, never in the file

Tools:
{tools}
Rules:
1. Start with an input node holding the task spelled out. Agents cannot ask questions, nobody answers them.
2. Any agent that needs facts off the web gets web_search and http_get, and its system_prompt must order it
   to open pages before reporting. Search results alone are not evidence. Add browser_get as well when the
   source is a modern site that renders with JavaScript, such as a job board or a dashboard.
   When the facts are spread over a whole site rather than one page, such as a careers board, a docs set
   or a listings index, give it crawl_site instead of making it fetch page after page: one call walks the
   site, obeys robots.txt and returns every page it read. Tell it in the system_prompt which site to start
   from and what must_match pattern the pages it wants will contain.
3. Only an agent node may carry a schema. Give the last agent one. It is a key on that agent node itself, indented under it beside model and
   tools, never at the top level of the file. Records inside it must include a link field. The engine checks
   every link against the pages that agent really visited and stamps verified true or false by itself, so do
   not put a verified field in the schema.
4. Build the schema around what the goal actually asks for: an object holding an array of records, each
   record carrying the fields a person reading this would want.
5. Research that should run constantly: alwaysOn true, the researcher mode async with its own interval,
   and an output node with a wait.
6. One job per agent. Chain them. End with an output node.
7. Send the result somewhere real when the goal implies it: a sink on the output node, with dedupe set to
   the field that identifies a record, so a workflow that runs forever never repeats itself.
8. Put an approval node before anything that sends, posts, pays or writes outside the workflow folder.
9. Use map: true when the goal is to process many records the same way, rather than one agent doing all of it.
10. File tools are locked to the workflow folder, so write results as plain names like report.csv. Ask for
    allow_paths only when the goal names a folder outside it, allow_shell only when the goal is to run
    commands, and allow_email only when the goal is to email someone.
11. Any figure, price, total, date or quote in the output must come from a tool, so list that tool in
    require_tools. A model asked for a sum without calculate will make one up.
12. Reach for the tool that fits the source: read_pdf, read_doc and read_table for documents a company keeps,
    sql_query for a database file, http_request for another system's API, rss_feed for a feed, now for the
    date, calculate for arithmetic, remember and recall to carry notes between runs.
13. Never invent a tool name, a model name or a node type.
"""


def _strip_fence(text):
    text = (text or "").strip()
    if text.startswith("```"):
        text = text.split("```")[1].strip()
        if text.startswith("yaml"):
            text = text[4:].strip()
    return text


def _tidy(data, models, model_name):
    """Drop invented tools and models. Only agent nodes carry tools, so a diff stays honest."""
    for node in data.get("nodes") or data.get("agents", []):
        if not isinstance(node, dict):
            continue
        if node.get("type", "agent") == "agent":
            node["tools"] = [t for t in node.get("tools", []) if t in BY_NAME]
            if node.get("model") not in models:
                node["model"] = model_name
        else:
            node.pop("tools", None)


def _rules(goal, model_name):
    models = [m.model for m in ollama.list().models]
    tools = "".join(f"  - {name}: {fn.__doc__.strip().splitlines()[0]}\n" for name, fn in BY_NAME.items())
    return SPEC.format(goal=goal, models=", ".join(models), tools=tools), models


def propose_workflow(user_goal: str, model_name: str = "qwen3-coder-next:latest"):
    """Write a workflow file for a goal and hand it back WITHOUT saving it."""
    try:
        prompt, models = _rules(user_goal, model_name)
        answer = _strip_fence(ollama.chat(model=model_name, stream=False,
                                          messages=[{"role": "user", "content": prompt}])["message"]["content"])
        data = yaml.safe_load(answer)
        if not isinstance(data, dict):
            return {"success": False, "error": "the model did not return a workflow"}
        _tidy(data, models, model_name)
        text = yaml.dump(data, default_flow_style=False, sort_keys=False)
        return {"success": True, "yaml": text, "warnings": validate(data),
                "name": data.get("name", "unnamed")}
    except Exception as e:
        return {"success": False, "error": str(e)}


def propose_edit(folder: str, instruction: str, model_name: str = "qwen3-coder-next:latest",
                 node: str = ""):
    """Rewrite an existing workflow from an instruction and hand it back WITHOUT saving it."""
    path = os.path.join(folder, "workflow.yaml")
    try:
        with open(path, "r") as f:
            current = f.read()
        prompt, models = _rules("(editing an existing workflow)", model_name)
        scope = f"The person is looking at the node '{node}'. Change that node unless they say otherwise.\n" if node else ""
        answer = _strip_fence(ollama.chat(model=model_name, stream=False, messages=[
            {"role": "user", "content": prompt},
            {"role": "user", "content": f"This is the current workflow:\n\n{current}\n\n{scope}"
             f"Change it as follows: {instruction}\nReturn the whole updated YAML, raw, nothing else."}
        ])["message"]["content"])
        data = yaml.safe_load(answer)
        if not isinstance(data, dict):
            return {"success": False, "error": "the model did not return a workflow"}
        _tidy(data, models, model_name)
        text = yaml.dump(data, default_flow_style=False, sort_keys=False)
        return {"success": True, "yaml": text, "current": current, "warnings": validate(data)}
    except Exception as e:
        return {"success": False, "error": str(e)}


ASK = """You are looking at one workflow in an agent orchestrator and answering its author.
Answer in plain words, under 180 words, no preamble, no markdown headings.

The workflow file:
{yaml}

What the last run did:
{run}

Question: {question}
"""


def answer_question(folder: str, question: str, run_summary: str = "",
                    model_name: str = "qwen3-coder-next:latest"):
    """Answer a question about a workflow and its last run. Writes nothing."""
    try:
        with open(os.path.join(folder, "workflow.yaml"), "r") as f:
            current = f.read()
        prompt = ASK.format(yaml=current[:6000], run=(run_summary or "it has not run yet")[:6000],
                            question=question)
        answer = ollama.chat(model=model_name, stream=False,
                             messages=[{"role": "user", "content": prompt}])["message"]["content"]
        return {"success": True, "answer": answer.strip()}
    except Exception as e:
        return {"success": False, "error": str(e)}


def create_workflow_from_ai(user_goal: str, model_name: str = "qwen3-coder-next:latest"):
    models = [m.model for m in ollama.list().models]
    tools = "".join(f"  - {name}: {fn.__doc__.strip().splitlines()[0]}\n" for name, fn in BY_NAME.items())
    prompt = SPEC.format(goal=user_goal, models=", ".join(models), tools=tools)
    try:
        response = ollama.chat(
            model=model_name,
            messages=[{"role": "user", "content": prompt}],
            stream=False
        )
        yaml_text = response["message"]["content"].strip()

        # Clean potential markdown wrappers
        if yaml_text.startswith("```"):
            yaml_text = yaml_text.split("```")[1].strip()
            if yaml_text.startswith("yaml"):
                yaml_text = yaml_text[4:].strip()

        workflow_data = yaml.safe_load(yaml_text)

        # drop any tool the AI invented, force a model that exists
        for node in workflow_data.get("nodes") or workflow_data.get("agents", []):
            node["tools"] = [t for t in node.get("tools", []) if t in BY_NAME]
            if node.get("type", "agent") == "agent" and node.get("model") not in models:
                node["model"] = model_name

        nodes = workflow_data.get("nodes") or workflow_data.get("agents", [])
        agents = [n for n in nodes if n.get("type", "agent") == "agent"]
        stray = workflow_data.pop("schema", None)  # models float the schema to the top level or onto output
        for node in nodes:
            if node.get("type", "agent") != "agent":
                if node.get("schema"):
                    stray = node.pop("schema")
                node.pop("tools", None)
        if stray and agents and not any(a.get("schema") for a in agents):
            agents[-1]["schema"] = stray
        for agent in agents:
            for record in (agent.get("schema") or {}).get("properties", {}).values():
                fields = record.get("items", {}).get("required")
                if fields and "verified" in fields:
                    fields.remove("verified")  # the engine stamps this, the model must not

        problems = validate(workflow_data)
        if problems:  # hand the complaints back once and let it fix its own file
            fixed = ollama.chat(model=model_name, stream=False, messages=[
                {"role": "user", "content": prompt},
                {"role": "assistant", "content": yaml_text},
                {"role": "user", "content": "That file has these problems:\n- " + "\n- ".join(problems)
                 + "\nReturn the whole corrected YAML, raw, nothing else."}])["message"]["content"].strip()
            if fixed.startswith("```"):
                fixed = fixed.split("```")[1].strip()
                if fixed.startswith("yaml"):
                    fixed = fixed[4:].strip()
            retried = yaml.safe_load(fixed)
            if isinstance(retried, dict) and len(validate(retried)) < len(problems):
                workflow_data = retried
                problems = validate(workflow_data)

        name = workflow_data.get("name", "unnamed")
        folder = os.path.join(WORKFLOWS_DIR, name)
        n = 2
        while os.path.exists(folder):  # never clobber an existing workflow
            folder = os.path.join(WORKFLOWS_DIR, f"{name}_{n}")
            n += 1
        os.makedirs(folder)
        filepath = os.path.join(folder, "workflow.yaml")
        with open(filepath, "w") as f:
            yaml.dump(workflow_data, f, default_flow_style=False, sort_keys=False)

        return {"success": True, "filepath": filepath, "warnings": problems}
    except Exception as e:
        return {"success": False, "error": str(e)}

def edit_workflow_from_ai(folder: str, instruction: str, model_name: str = "qwen3-coder-next:latest"):
    """Rewrite an existing workflow.yaml from a plain instruction, validated before it is saved."""
    path = os.path.join(folder, "workflow.yaml")
    try:
        with open(path, "r") as f:
            current = f.read()
        models = [m.model for m in ollama.list().models]
        tools = "".join(f"  - {name}: {fn.__doc__.strip().splitlines()[0]}\n" for name, fn in BY_NAME.items())
        rules = SPEC.format(goal="(editing an existing workflow)", models=", ".join(models), tools=tools)
        answer = ollama.chat(model=model_name, stream=False, messages=[
            {"role": "user", "content": rules},
            {"role": "user", "content": f"This is the current workflow:\n\n{current}\n\n"
             f"Change it as follows: {instruction}\nReturn the whole updated YAML, raw, nothing else."}
        ])["message"]["content"].strip()
        if answer.startswith("```"):
            answer = answer.split("```")[1].strip()
            if answer.startswith("yaml"):
                answer = answer[4:].strip()
        data = yaml.safe_load(answer)
        if not isinstance(data, dict):
            return {"success": False, "error": "model did not return a workflow"}
        for node in data.get("nodes") or data.get("agents", []):
            node["tools"] = [t for t in node.get("tools", []) if t in BY_NAME]
            if node.get("type", "agent") == "agent" and node.get("model") not in models:
                node["model"] = model_name
        problems = validate(data)
        with open(path, "w") as f:
            yaml.dump(data, f, default_flow_style=False, sort_keys=False)
        return {"success": True, "filepath": path, "warnings": problems}
    except Exception as e:
        return {"success": False, "error": str(e)}


if __name__ == "__main__":
    print(create_workflow_from_ai(user_goal=input("enter workflow: ")))
