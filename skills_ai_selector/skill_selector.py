import os
from mistralai import Mistral
from dotenv import load_dotenv

with open("skills.txt") as f:
    skills = f.read()

with open("job_description.txt", encoding="utf-8") as f:
    job_description = f.read()

# load the api key from the .env file
load_dotenv()
api_key = os.getenv("MISTRAL_API_KEY")

model = "mistral-large-latest"

client = Mistral(api_key=api_key)

messages = [
        {
            "role": "system",
            "content": "You are an expert CV and cover letter reviewer and consultant, focused on skills match."
        },
        {
            "role": "user",
            "content": """ Here are my skills, formatted as 
                # Section
                skill rating
                - sub_skill rating
    
            """ + skills + """
            
            And here is the job description:
            """ + job_description + """
            Your task is to respond with four sorted lists skills, each of at least 20 items
            Write for each skill the following 4 colums:
            -<importance rank>(1-20, sequential), <skill name>, <skill user rating>(1-5 if skill is present in user list, 0 otherwise), <reason for importance in job description>, <importance in job description>(1-5) 
            Sort the skills by the product of the two ratings, descending (but show the ratings separately, not the product!).
            1. Explicit match:
            the skills that are explictitly mentioned in both the skill list and the job description: EXPLICIT SKILL, EXPLICIT JOB
            2. Implicit in user list:
            the skills that are NOT in the skill list, but are in the job description, and it looks they should be among the user skills given the other skills in the list: IMPLICIT SKILL, EXPLICIT JOB
            - example: an use with PowerBI should be expected to know Excel. An user with C++ experience likely knows Git.
            3. Implicit in job description:
            the skills that are are not in the job description, but are in the skills list, and seem like they could be appreciated: EXPLICIT SKILL, IMPLICIT JOB
            - example: a job that asks for PowerBI might apprecite also knowing the competitor Tableau. A request for C++ might appreciate knowing the Abseil C++ libray.
            4. Missing:
            the skills that are in the job description, but are not in the user list, and are also not implied: NO SKILL, EXPLICIT JOB
            For example if the skills lists only programming languages and the job asks for law knowledge, that doesn't seem like an acciental omission but an actual missing skill.

            Repeat the full description of what the list should be before writing it.
            """
        }
    ]

chat_response = client.chat.complete(
    model= model,
    messages = messages
)

response_content = chat_response.choices[0].message.content

print(response_content)
control = input("Letter ready to examine? (y/n): ")

if control.lower() != "y":
    print("Exiting")
    exit()

with open("letter.txt", "r") as f:
    letter = f.read()

messages.append({
    "role": "assistant",
    "content": response_content
})
messages.append({
    "role": "user",
    "content": """Ok, I wrote this letter:

    """ + letter + """
    
    Is it complete?
    Any requested skill I forgot to mention I have, or that I don't have and I should address?
    
    Any suggestion?
    """
})

chat_response_2 = client.chat.complete(
    model= model,
    messages = messages
)

print(chat_response_2.choices[0].message.content)