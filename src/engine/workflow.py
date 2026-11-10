from agent import Agent

#Dead code
"""
#agent1 = Agent("qwen3-coder-next:latest","agent1")
#agent2 = Agent("qwen3-coder-next:latest", "agent2")

if agent1.spin_up():
    ai_input = (agent1.chat("return mock data of webreseqrch of stock data and news including fake prices multiple stocks",""))
    print(ai_input)
    output = (agent2.chat("only return Json format for every stock ticker, price, confidence score umber up or down 1  being max -1 being bottom", ai_input))
    print(output_


if agent1.spin_up():
    ai_input = (agent1.chat("return mock data of webreseqrch of stock data and news including fake prices multiple stocks",""))
    print(ai_input)
    output = (agent2.chat("only return Json format for every stock ticker, price, confidence score umber up or down 1  being max -1 being bottom", ai_input))
    print(output)

"""

# src/engine/workflow.py (lines 1–78)
import yaml

from agent import Agent


class Workflow:
    def __init__(self, yaml_path):
        with open(yaml_path, "r") as f:
            data = yaml.safe_load(f)

        agents = [
            Agent(
                model=agent["model"],
                name=agent["name"],
                system_prompt=agent.get("system_prompt", "")
            )
            for agent in data.get("agents", [])
        ]

        self.name = data.get("name", "unnamed_workflow")
        self.agents = agents
        self.purpose = data.get("purpose", "")
        self.alwaysOn = data.get("alwaysOn", False)

    def run(self, tasks=None):
        if not tasks:
            # Chain all agents in order (YAML order), passing output to next input
            current_input = ""
            for agent in self.agents:
                response = agent.chat(current_input)
                current_input = response
            print(current_input)  # print only the final result
        else:
            # If tasks provided, run each task independently
            results = []
            for task in tasks:
                agent_name = task.get("agent")
                user_msg = task.get("user_message", "")
                agent = next((a for a in self.agents if a.name == agent_name), None)
                if not agent:
                    results.append(f"error: agent '{agent_name}' not found")
                    continue
                response = agent.chat(user_msg)
                results.append(response)
            return results


worker = Workflow("/home/dsneedy/Desktop/AGENT-WORKFLOW-ORCHESTRATOR/src/engine/workflows/stock_analysis_pipeline.yaml")
worker.run()
