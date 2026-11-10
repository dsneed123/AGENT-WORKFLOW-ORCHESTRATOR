# src/engine/workflow_creation.py
import os
import yaml

# src/engine/workflow_creation.py (lines 5–16)
def create_workflow_from_ai(user_goal: str, model_name: str = "qwen3-coder-next:latest"):
    prompt = (
        f"You are an expert YAML architect for multi-agent workflows.\n"
        f"Create a valid workflow YAML to accomplish this goal: \"{user_goal}\".\n\n"
        f"- Save the file in `workflows/` directory at project root.\n"
        f"- Filename: `<workflow_name>.yaml`, e.g., `stock_analysis.yaml`.\n"
        f"- Every agent **must export final output as JSON** (include 'export_json: true' in its config).\n\n"
        f"- Use this schema:\n```yaml\nname: workflow_name\npurpose: clear one-sentence description\nagents:\n  - model: ollama_model_id\n    name: unique_agent_name\n    system_prompt: role (≤10 words, zero fluff)\n    export_json: true (optional, default false)\n```\n"
        f"- Agent order matters — each agent processes the previous output.\n"
        f"- System prompts must be *direct*, e.g., 'Mock stock prices', 'Analyze and justify buy/sell/hold' — no intros, disclaimers, or filler words like 'sure', 'here's', etc.\n"
        f"- Return only the raw YAML block (no markdown, no explanation)."
    )
    try:
        import ollama
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

        os.makedirs("workflows", exist_ok=True)
        filename = f"{workflow_data.get('name', 'unnamed')}.yaml"
        filepath = f"workflows/{filename}"
        with open(filepath, "w") as f:
            yaml.dump(workflow_data, f, default_flow_style=False)

        return {"success": True, "filepath": filepath}
    except Exception as e:
        return {"success": False, "error": str(e)}

# src/engine/workflow_creation.py (lines 44–48)
workflow = input("enter workflow: ")
result = create_workflow_from_ai(user_goal=workflow)
print(result)

create_workflow_from_ai(user_goal=workflow)