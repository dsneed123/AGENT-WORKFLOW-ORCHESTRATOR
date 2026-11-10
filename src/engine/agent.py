import ollama
class Agent:
    def __init__(self, model, name, system_prompt=""):
        self.system_prompt=system_prompt
        self.model = model
        self.name = name

    def spin_up(self):
        try:
            ollama.show(self.model)
            return True
        except Exception as e:
            print(f"error loading model {self.model} : {e}")
            return False


    def chat(self, user_message):
        try:
            print(f"{self.name} is working ...")
            response = ollama.chat(
                model=self.model,
                stream=False,
                messages=[{"role": "system",
                "content": self.system_prompt,
                },{
                    "role" : "user",
                    "content": user_message,
                }]
            )
            return response["message"]["content"]
        except Exception as e:
            return f"error: {e}"


    

