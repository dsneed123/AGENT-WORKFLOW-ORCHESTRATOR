import os
import sys

import ollama

sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tools"))
from browser import browser_get
from docs import read_doc, read_pdf, read_table, search_files, sql_query
from files import list_dir, read_file, write_file
from memory import recall, remember
from net import http_request, rss_feed, screenshot, send_email
from research import http_get, web_search
from util import calculate, now
from shell import run_shell_command

PIPELINE_RULES = (
    "You are one stage in an automated pipeline. No human is reading this and nobody will answer you. "
    "Never ask a question, never offer choices, never say what you could do. "
    "If you need data, call your tools and get it yourself. Output the result only."
)
TOOLS = [run_shell_command, read_file, write_file, list_dir, search_files,
         http_get, web_search, browser_get, screenshot,
         http_request, rss_feed, send_email,
         read_pdf, read_doc, read_table, sql_query,
         remember, recall, now, calculate]
BY_NAME = {f.__name__: f for f in TOOLS}

class Agent:
    def __init__(self, model, name, system_prompt="", tools=TOOLS, output_format=None, dispatch=None,
                 require_tools=()):
        self.system_prompt = f"{system_prompt}\n\n{PIPELINE_RULES}".strip()
        self.model = model
        self.name = name
        self.tools = tools
        self.output_format = output_format
        self.dispatch = dispatch or {}  # extra tools by name, e.g. everything an MCP server offers
        self.require_tools = list(require_tools)  # answering without calling these is a fabrication
        self.calls = []

    def spin_up(self):
        try:
            ollama.show(self.model)
            return True
        except Exception as e:
            print(f"error loading model {self.model} : {e}")
            return False


    def chat(self, user_message):
        messages = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": user_message},
        ]
        by_name = {f.__name__: f for f in self.tools if callable(f)}
        by_name.update(self.dispatch)
        self.calls = []
        shaping, nagged = False, 0
        try:
            print(f"\033[38;5;166m▸ {self.name}\033[0m \033[2mworking ...\033[0m")
            for _ in range(12):
                message = ollama.chat(
                    model=self.model,
                    stream=False,
                    messages=messages,
                    tools=self.tools,
                    format=self.output_format if shaping else None,
                )["message"]
                messages.append(message)
                calls = message.get("tool_calls") or []
                if not calls:
                    missing = [t for t in self.require_tools
                               if t not in {c["tool"] for c in self.calls}]
                    if missing and nagged < 2:
                        nagged += 1
                        messages.append({"role": "user", "content":
                                         f"You answered without calling {', '.join(missing)}. "
                                         f"Call {missing[0]} now and base your answer on what it returns. "
                                         f"Do not state any figure you have not got from a tool."})
                        continue
                    if missing:
                        return (f"error: {self.name} answered without calling {', '.join(missing)}, "
                                f"so the answer is not backed by anything")
                    if self.output_format and not shaping:
                        # tools are done, now make it answer in the required shape
                        messages.append({"role": "user", "content": "Return that result as JSON only."})
                        shaping = True
                        continue
                    return message["content"]
                for call in calls:
                    name = call["function"]["name"]
                    print(f"  \033[2m└ {name}({call['function']['arguments']})\033[0m")
                    fn = by_name.get(name)
                    output = fn(**call["function"]["arguments"]) if fn else f"error: unknown tool {name}"
                    self.calls.append({"tool": name, "args": call["function"]["arguments"],
                                       "result": str(output)[:2000]})
                    messages.append({"role": "tool", "name": name, "content": str(output)})
            return "error: tool loop limit reached"
        except Exception as e:
            return f"error: {e}"
