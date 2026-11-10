from agent import Agent
agent1 = Agent("qwen3-coder-next:latest","agent1")
agent2 = Agent("qwen3-coder-next:latest", "agent2")

class Workflow:
    def __init__(self, agents, purpose, alwaysOn):

    def run():
        return 0


if agent1.spin_up():
    ai_input = (agent1.chat("return mock data of webreseqrch of stock data and news including fake prices multiple stocks",""))
    print(ai_input)
    output = (agent2.chat("only return Json format for every stock ticker, price, confidence score umber up or down 1  being max -1 being bottom", ai_input))
    print(output)

def import_workflow(yaml):
    with open(yaml, "r") as f:
        config = yaml