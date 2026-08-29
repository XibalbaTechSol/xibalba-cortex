import json
import subprocess
import logging
from pathlib import Path

# Need to run: uv add sentence-transformers
from sentence_transformers import SentenceTransformer
from xibalba_cortex.store import GraphStore, EMBEDDING_MODEL_ID, EMBEDDING_DIM

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("process_queue")

def run_hermes_inference(text: str) -> dict:
    prompt = f"""
Analyze the following text and extract metadata and relationships according to the PARA (Projects, Areas, Resources, Archives) framework.
Return ONLY a valid JSON object with the following structure:
{{
  "labels": [ "Label1", "Label2" ],
  "relationships": [
    {{ "subject": "EntityA", "predicate": "RELATES_TO", "object": "EntityB" }}
  ],
  "summary": "A brief summary of the content."
}}

Text to analyze:
{text}
"""
    logger.info("Running hermes -z inference...")
    result = subprocess.run(
        ["hermes", "-z", prompt], 
        capture_output=True, 
        text=True,
        check=False
    )
    if result.returncode != 0:
        logger.error(f"Hermes failed: {result.stderr}")
        return {}
    
    output = result.stdout.strip()
    # Attempt to parse JSON. Sometimes LLMs wrap in ```json ... ```
    if "```json" in output:
        output = output.split("```json")[1].split("```")[0].strip()
    elif "```" in output:
        output = output.split("```")[1].strip()
    
    try:
        return json.loads(output)
    except Exception as e:
        logger.error(f"Failed to parse JSON from Hermes: {e}\nRaw output: {output}")
        return {}

def main():
    home_dir = Path.home() / ".hermes" / "xibalba-cortex"
    store = GraphStore(home_dir)
    
    logger.info(f"Loading embedding model: {EMBEDDING_MODEL_ID}")
    model = SentenceTransformer(EMBEDDING_MODEL_ID)
    
    pending_tasks = store.list_inference_tasks(status="pending")
    logger.info(f"Found {len(pending_tasks)} pending tasks.")
    
    for task in pending_tasks:
        task_id = task["id"]
        task_type = task["task_type"]
        subject_id = task["subject_id"]
        subject_type = task["subject_type"]
        
        logger.info(f"Processing task {task_id} ({task_type} on {subject_type} {subject_id})")
        
        # 1. Fetch content
        content = ""
        memory_id = None
        if subject_type == "memory":
            try:
                memory = store.get_memory(subject_id)
                content = memory["content"]
                memory_id = subject_id
            except KeyError:
                logger.warning(f"Memory {subject_id} not found.")
                continue
        elif subject_type == "session":
            # For sessions, we need to gather exchanges
            try:
                exchanges = store.session_exchanges(subject_id)
                lines = []
                for ex in exchanges:
                    lines.append(f"Prompt: {ex.get('prompt', '')}")
                    lines.append(f"Response: {ex.get('response', '')}")
                content = "\n".join(lines)
                # Session summaries generate a new memory
            except Exception as e:
                logger.warning(f"Session {subject_id} failed: {e}")
                continue
        
        if not content.strip():
            logger.warning(f"Empty content for task {task_id}, skipping.")
            continue
            
        # 2. Run inference
        inference_result = run_hermes_inference(content)
        
        # 3. Compute Embedding if it's a memory
        embedding = None
        if memory_id:
            logger.info("Computing embeddings...")
            embedding = model.encode(content).tolist()
            if len(embedding) == EMBEDDING_DIM:
                store.store_embedding(memory_id, EMBEDDING_MODEL_ID, embedding)
                logger.info(f"Stored embedding for {memory_id}")
        
        # 4. Save metadata / relationships
        # The exact implementation depends on xibalba_cortex methods
        # For now, we will complete the inference task with the output payload
        if inference_result:
            store.complete_inference_task(
                task_id, 
                output_payload=inference_result, 
                error=None
            )
            logger.info(f"Completed task {task_id}")
        else:
            store.complete_inference_task(
                task_id,
                output_payload=None,
                error="Failed to extract valid JSON from Hermes."
            )
            logger.error(f"Failed task {task_id}")

if __name__ == "__main__":
    main()
