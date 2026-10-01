"""Responses adapter preserving the application's established tool interface."""
import json,asyncio,copy,os
import httpx
from fastapi import HTTPException

LOCAL_LOCK=asyncio.Lock()
def local_messages(messages):
    """Preserve task/rubric and system evidence; drop old turns before truncation."""
    local=[]
    for m in messages:
        v=copy.deepcopy({k:val for k,val in m.items() if not k.startswith('_')})
        for call in v.get('tool_calls',[]):
            args=call.get('function',{}).get('arguments')
            if isinstance(args,str):
                try:call['function']['arguments']=json.loads(args)
                except ValueError:raise HTTPException(400,'Invalid local tool arguments')
        local.append(v)
    budget=24000
    while len(json.dumps(local,ensure_ascii=False))>budget and len(local)>2:
        # Remove a whole old user/assistant/tool exchange, never half a tool call.
        next_user=next((i for i in range(2,len(local)) if local[i].get('role')=='user'),len(local)-1)
        local=local[:1]+local[next_user:]
    if len(json.dumps(local,ensure_ascii=False))>budget:
        raise HTTPException(400,'This request exceeds the local model context budget. Shorten the pasted material or split the task; the rubric and samples were not silently cut off.')
    return local

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
        local=local_messages(messages)
        writer=any('voice-matching writing assistant' in str(m.get('content','')) for m in local[:1])
        # This PC's GPU supports 8K context; 16K exhausted Vulkan memory.
        # Reserve context for output using a conservative UTF-8 size estimate.
        estimated_prompt=(len(json.dumps(local,ensure_ascii=False).encode('utf-8'))+2)//3
        output_budget=min(max_tokens,3500,max(256,8192-estimated_prompt-512))
        gpu_layers=int(os.getenv('LOCAL_AI_GPU_LAYERS','24'))
        payload={'model':model,'messages':local,'stream':False,'think':False,'options':{'num_ctx':8192,'num_gpu':gpu_layers,'num_batch':128,'num_predict':output_budget,'temperature':0.4 if writer else 0.15},'keep_alive':'15m'}
        if tools:payload['tools']=tools
        try:
            async with LOCAL_LOCK:
                async with httpx.AsyncClient(timeout=360) as client:r=await client.post('http://127.0.0.1:11434/api/chat',json=payload)
            if r.status_code>=400:raise HTTPException(502,'Local AI unavailable (HTTP '+str(r.status_code)+'). Check Ollama and installed model; no paid fallback was used.')
            data=r.json();message=data['message']
            if data.get('done_reason')=='length':raise HTTPException(502,'Local AI reached its output limit. Request a shorter draft or one section at a time; no incomplete draft was saved.')
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
