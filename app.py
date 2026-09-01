import discord
import httpx
import json
import fastapi
import uvicorn
import os
import random
import time
import asyncio
import urllib.parse
import datetime

from discord.ext import commands
from fastapi import Query
from fastapi.responses import HTMLResponse

# Load configuration
with open('config.json', 'r') as f:
    stuff = json.load(f)

token = stuff.get('token')
secret = stuff.get('secret')
id = stuff.get('id')
redirect = stuff.get('redirect')
api = stuff.get('api_endpoint', 'https://discord.com/api/v10')
logs = stuff.get('logs', [])

app = fastapi.FastAPI()
intents = discord.Intents.all()
client = commands.Bot(command_prefix='!', intents=intents)
client.remove_command('help')

@client.event
async def on_ready():
    print(f"Connected as: {client.user}")

@client.command()
async def count(ctx):
    unique_count = 0
    if os.path.exists('auths.txt'):
        with open('auths.txt', 'r') as f:
            unique_users = set()
            for line in f:
                try:
                    user_id, _, _ = line.strip().split(',')
                    unique_users.add(user_id)
                except Exception:
                    continue
            unique_count = len(unique_users)
    
    embed = discord.Embed(
        title="🔢 Auth Count",
        description=f"Total unique auths: {unique_count}",
        color=discord.Color.green(),
        timestamp=datetime.datetime.now(datetime.timezone.utc)
    )
    footer_icon = client.user.avatar.url if client.user and client.user.avatar else None
    embed.set_footer(text="Authix Bot • Service", icon_url=footer_icon)
    await ctx.send(embed=embed)

@app.get("/")
async def home():
    return {"status": "Authix is running"}

@app.get('/callback')
async def authenticate(code: str = Query(...)):
    try:
        data = {
            'client_id': id,
            'client_secret': secret,
            'grant_type': 'authorization_code',
            'code': code,
            'redirect_uri': redirect,
            'scope': 'identify guilds.join'
        }

        async with httpx.AsyncClient() as http_client:
            response = await http_client.post(f'{api}/oauth2/token', data=data)
            response.raise_for_status()
            details = response.json()

            access_token = details['access_token']
            refresh_token = details['refresh_token']

            headers = {'Authorization': f'Bearer {access_token}'}
            user_res = await http_client.get(f'{api}/users/@me', headers=headers)
            user_info = user_res.json()
            user_id = user_info['id']
            username = user_info.get('username', 'unknown')

        lines = []
        if os.path.exists('auths.txt'):
            with open('auths.txt', 'r') as file:
                lines = file.readlines()

        found = False
        for i, line in enumerate(lines):
            if line.startswith(f"{user_id},"):
                lines[i] = f'{user_id},{access_token},{refresh_token}\n'
                found = True
                break

        if not found:
            lines.append(f'{user_id},{access_token},{refresh_token}\n')

        with open('auths.txt', 'w') as file:
            file.writelines(lines)

        embed = discord.Embed(
            title="✅ Authentication Successful",
            description=f"Welcome, {username}!",
            color=discord.Color.blue(),
            timestamp=datetime.datetime.now(datetime.timezone.utc)
        )
        embed.add_field(name="User ID", value=user_id, inline=True)

        if logs:
            hook_url = random.choice(logs)
            async with httpx.AsyncClient() as http_client:
                await http_client.post(hook_url, json={'embeds': [embed.to_dict()]})

        html_content = f"""
        <html>
            <body style="background-color: #2f3136; color: white; font-family: sans-serif; text-align: center; padding: 50px;">
                <h1>✅ Authentication Successful</h1>
                <p>Welcome, {username}! You can close this tab.</p>
            </body>
        </html>
        """
        return HTMLResponse(content=html_content)

    except Exception as e:
        html_content = f"""
        <html>
            <body style="background-color: #2f3136; color: white; font-family: sans-serif; text-align: center; padding: 50px;">
                <h1>❌ Authentication Failed</h1>
                <p>Error: {str(e)}</p>
            </body>
        </html>
        """
        return HTMLResponse(content=html_content, status_code=500)

@client.command(name='refresh')
async def refresh(ctx):
    start_time = time.time()
    refreshed, failed = [], []

    if not os.path.exists('auths.txt'):
        await ctx.send("No `auths.txt` file found.")
        return

    with open('auths.txt', 'r') as f:
        lines = f.readlines()

    unique_tokens = {}
    for line in lines:
        try:
            u_id, a_tok, r_tok = line.strip().split(',')
            unique_tokens[u_id] = (a_tok, r_tok)
        except Exception:
            continue

    total = len(unique_tokens)
    if total == 0:
        await ctx.send("No valid tokens to refresh.")
        return

    msg = await ctx.send(f"Refreshing {total} tokens...")
    new_lines = []

    async with httpx.AsyncClient() as http_client:
        for u_id, (a_tok, r_tok) in unique_tokens.items():
            try:
                data = {
                    'client_id': id,
                    'client_secret': secret,
                    'grant_type': 'refresh_token',
                    'refresh_token': r_tok,
                }
                res = await http_client.post(f'{api}/oauth2/token', data=data)
                if res.status_code in (200, 201):
                    tokens = res.json()
                    new_lines.append(f"{u_id},{tokens['access_token']},{tokens['refresh_token']}\n")
                    refreshed.append(u_id)
                else:
                    failed.append(u_id)
            except Exception:
                failed.append(u_id)

    with open('auths.txt', 'w') as f:
        f.writelines(new_lines)

    total_time = int(time.time() - start_time)
    await msg.edit(content=f"Refresh Complete! Success: {len(refreshed)} | Failed: {len(failed)} | Time: {total_time}s")

@client.command(name='pull')
async def pull(ctx, amount: int):
    if not os.path.exists('auths.txt'):
        await ctx.send("No auths available.")
        return

    with open('auths.txt', 'r') as file:
        lines = file.readlines()

    user_list = []
    for line in lines:
        try:
            u_id, a_tok, r_tok = line.strip().split(',')
            user_list.append((u_id, a_tok))
        except Exception:
            continue

    random.shuffle(user_list)
    added, failed = 0, 0
    msg = await ctx.send(f"Pulling {amount} members...")

    async with httpx.AsyncClient() as http_client:
        while added < amount and user_list:
            u_id, a_tok = user_list.pop()
            url = f"{api}/guilds/{ctx.guild.id}/members/{u_id}"
            headers = {"Authorization": f"Bot {token}", "Content-Type": "application/json"}
            
            res = await http_client.put(url, headers=headers, json={"access_token": a_tok})
            if res.status_code in (201, 204):
                added += 1
            else:
                failed += 1
            await asyncio.sleep(0.5)

    await msg.edit(content=f"Pull Finished! Added: {added} | Failed: {failed}")

@client.command(name="auth_link")
async def auth_link(ctx):
    params = {
        'client_id': id,
        'response_type': 'code',
        'redirect_uri': redirect,
        'scope': 'identify guilds.join'
    }
    url = "https://discord.com/oauth2/authorize?" + urllib.parse.urlencode(params)
    await ctx.send(f"Authentication Link: {url}")

# Dual-Service Startup Logic
async def main():
    port = int(os.environ.get("PORT", 10000))
    config = uvicorn.Config(app, host="0.0.0.0", port=port, log_level="info")
    server = uvicorn.Server(config)

    # Run FastAPI and Discord Bot together cleanly
    await asyncio.gather(
        server.serve(),
        client.start(token)
    )

if __name__ == "__main__":
    asyncio.run(main())
