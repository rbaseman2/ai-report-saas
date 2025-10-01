from services.openai_client import get_client

SYSTEM = "You write concise, executive-ready business summaries. Use plain English and avoid fluff."

def generate_exec_summary(kpis: dict, context: dict, temperature=0.4) -> str:
    client = get_client()
    content = f"KPIs: {kpis}\nContext: {context}\nWrite a 150-220 word executive summary."
    resp = client.chat.completions.create(
        model="gpt-4o-mini",  # or another model you have access to
        temperature=temperature,
        messages=[
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": content},
        ],
        max_tokens=500,
    )
    return resp.choices[0].message.content.strip()
