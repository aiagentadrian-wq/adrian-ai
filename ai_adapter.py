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
    if provider['base_url'].rstrip('/')=='http://127.0.0.1:11434/v1':
        # Exact loopback only. No paid fallback and no hidden desktop/shell access.
        local=[]
        for m in messages:
            v={k:val for k,val in m.items() if not k.startswith('_')}
            if isinstance(v.get('content'),str):
                limit=4500 if v.get('role')=='system' else 9000 if m is messages[-1] else 500
                if len(v['content'])>limit:v['content']=v['content'][:limit]+' [truncated; request focused evidence if needed]'
            for call in v.get('tool_calls',[]):
                if isinstance(call.get('function',{}).get('arguments'),str):
                    call['function']=dict(call['function'],arguments=json.loads(call['function']['arguments']))
            local.append(v)
        payload={'model':model,'messages':local,'stream':False,'think':False,'options':{'num_ctx':8192,'num_predict':min(max_tokens,1400),'temperature':0.2},'keep_alive':'15m'}
        if tools:payload['tools']=tools
        try:
            async with httpx.AsyncClient(timeout=180) as client:r=await client.post('http://127.0.0.1:11434/api/chat',json=payload)
            if r.status_code>=400:raise HTTPException(502,'Local AI unavailable (HTTP '+str(r.status_code)+'). Check Ollama and installed model; no paid fallback was used.')
            data=r.json();message=data['message']
            for i,call in enumerate(message.get('tool_calls',[])):
                call.setdefault('id','local-'+str(i));call.setdefault('type','function')
                if not isinstance(call['function'].get('arguments'),str):call['function']['arguments']=json.dumps(call['function'].get('arguments',{}))
            return {'choices':[{'message':message}],'usage':{'prompt_tokens':data.get('prompt_eval_count',0),'completion_tokens':data.get('eval_count',0)},'model':model}
        except httpx.RequestError:raise HTTPException(502,'Local AI is not responding. Start Ollama; no paid fallback was used.')
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
