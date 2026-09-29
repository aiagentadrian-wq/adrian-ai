"""Responses adapter preserving the application's established tool interface."""
import json
import httpx
from fastapi import HTTPException

def response_input(messages):
    items=[]
    for message in messages:
        role=message.get('role','user')
        if role=='tool':
            items.append({'type':'function_call_output','call_id':message['tool_call_id'],'output':str(message.get('content',''))})
        elif message.get('_response_output'):
            items.extend(message['_response_output'])
        else:
            if message.get('content'):items.append({'role':role,'content':message['content']})
            for call in message.get('tool_calls',[]):
                items.append({'type':'function_call','call_id':call['id'],'name':call['function']['name'],'arguments':call['function']['arguments']})
    return items

def normalize(data):
    text=[];calls=[]
    for item in data.get('output',[]):
        if item.get('type')=='message':
            for part in item.get('content',[]):
                if part.get('type')=='output_text':text.append(part['text'])
                elif part.get('type')=='refusal':text.append(part.get('refusal',''))
        elif item.get('type')=='function_call':
            calls.append({'id':item['call_id'],'type':'function','function':{'name':item['name'],'arguments':item['arguments']}})
    message={'role':'assistant','content':'\n'.join(text),'_response_output':data.get('output',[])}
    if calls:message['tool_calls']=calls
    return {'choices':[{'message':message}],'usage':data.get('usage',{}),'model':data.get('model'),'status':data.get('status')}

async def call(provider,messages,key,tools=None,max_tokens=1400):
    model=provider['model']
    use_responses=provider['base_url'].rstrip('/')=='https://api.openai.com/v1' and (model.startswith('gpt-5') or model.startswith('gpt-6') or model.startswith('o'))
    if use_responses:
        payload={'model':model,'input':response_input(messages),'max_output_tokens':max(6000,max_tokens+3000),'store':False,'include':['reasoning.encrypted_content'],'reasoning':{'effort':'medium'}}
        if tools:
            payload['tools']=[{'type':'function',**t['function'],'strict':False} for t in tools]
            payload['tool_choice']='auto'
        endpoint='/responses'
    else:
        payload={'model':model,'messages':[{k:v for k,v in m.items() if not k.startswith('_')} for m in messages],'max_tokens':max_tokens}
        if tools:payload.update(tools=tools,tool_choice='auto')
        endpoint='/chat/completions'
    try:
        async with httpx.AsyncClient(timeout=120) as client:
            r=await client.post(provider['base_url'].rstrip('/')+endpoint,headers={'Authorization':'Bearer '+key},json=payload)
        if r.status_code>=400:raise HTTPException(502,f'AI provider request failed (HTTP {r.status_code}). Check API Center for access or quota status.')
        data=r.json()
        if use_responses:
            if data.get('status')!='completed':raise HTTPException(502,'AI response was incomplete. Retry with a shorter request; no completed result was recorded.')
            return normalize(data)
        return data
    except httpx.RequestError:raise HTTPException(502,'AI provider unreachable. Check API Center.')
