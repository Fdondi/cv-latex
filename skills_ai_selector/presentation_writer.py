import os
from mistralai import Mistral
from dotenv import load_dotenv

with open("job_description.txt", encoding="utf-8") as f:
    job_description = f.read()

with open("cv.txt", encoding="utf-8") as f:
    cv = f.read()

# load the api key from the .env file
load_dotenv()
api_key = os.getenv("MISTRAL_API_KEY")

model = "mistral-large-latest"

client = Mistral(api_key=api_key)

messages = [
        {
            "role": "system",
            "content": """You are an expert CV consultant, focused on brief personal presentations ('Who I am'). You always reply with 4-5 lines, the elevator pitch I might give to a recruiter.
            This pitch should never mention the specific company or job, nor any specific competence that is already in the CV or cover letter. It is NOT an openly tailored cover letter; it should sound like a general introduction.
            It should focus on who I am as a person and professional, besides the specific skills and experiences that will be addressed better later. It should be a good mix of professional and personal, and should be engaging and memorable.
            This is my default CV:
            
            """ + cv
        },
        {
            "role": "user",
            "content": "<job offer from a large company focused on software development>"
        },
        {
            "role": "assistant",
            "content": "As a seasoned software developer, I bring a wealth of experience in developing robust software solutions. The post-Covid time has been hectic, but my diverse professional background gave me the experience to be immediately effective with all types of tools and processes. Now however I’m aiming at a stable position where I can grow long-term. I’m known among my peers and supervisors for being a reliable, intelligent, and friendly colleague, one who is always ready to take on responsibility and contribute to the team’s success."
        },
        {
            "role": "user",
            "content": "<Job offer from a company that needs a data scientist>"
        },
        {
            "role": "assistant",
            "content": "Ten years ago code was opening dazzling perspectives, now it’s data pipelines and machine learning. Building on my solid programming experience, and my diverse professional background giving me the experience to be immediately effective with all types of tools and processes, I’m very excited to pivot to this new world. I’m known among my peers and supervisors for being a reliable, intelligent, and friendly colleague, one who is always ready to take on responsibility and contribute to the team’s success."
        },
        {
            "role": "user",
            "content": job_description
        },
]

chat_response = client.chat.complete(
    model= model,
    messages = messages
)

print(chat_response.choices[0].message.content)