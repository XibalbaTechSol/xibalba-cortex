import argparse
import json
import subprocess
import logging
from pathlib import Path

# Requires: uv add sentence-transformers
from sentence_transformers import SentenceTransformer
from xibalba_cortex.store import GraphStore, EMBEDDING_MODEL_ID, EMBEDDING_DIM

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("manual_inference")

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
    logger.info("Running hermes -z inference (this may take a moment)...")
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
    if "```json" in output:
        output = output.split("```json")[1].split("```")[0].strip()
    elif "```" in output:
        output = output.split("```")[1].strip()
    
    try:
        return json.loads(output)
    except Exception as e:
        logger.error(f"Failed to parse JSON from Hermes: {e}\nRaw output: {output}")
        return {}

def get_content(store: GraphStore, subject_type: str, subject_id: str) -> tuple[str, str]:
    """Returns (content_text, memory_id)"""
    if subject_type == "memory":
        try:
            mem = store.get_memory(subject_id)
            return mem["content"], subject_id
        except KeyError:
            return "", ""
    elif subject_type == "session":
        try:
            exchanges = store.session_exchanges(subject_id)
            lines = []
            for ex in exchanges:
                lines.append(f"Prompt: {ex.get('prompt', '')}")
                lines.append(f"Response: {ex.get('response', '')}")
            return "\n".join(lines), ""
        except Exception:
            return "", ""
    return "", ""

def compute_embedding(store: GraphStore, memory_id: str, content: str):
    logger.info(f"Loading embedding model: {EMBEDDING_MODEL_ID}...")
    model = SentenceTransformer(EMBEDDING_MODEL_ID)
    logger.info(f"Computing embeddings for memory {memory_id}...")
    embedding = model.encode(content).tolist()
    if len(embedding) == EMBEDDING_DIM:
        store.store_embedding(memory_id, EMBEDDING_MODEL_ID, embedding)
        logger.info(f"✅ Stored {EMBEDDING_DIM}-dim embedding for {memory_id}")
    else:
        logger.error("Embedding dimension mismatch!")

def main():
    parser = argparse.ArgumentParser(description="Manual Inference & Embedding Tool for Xibalba Cortex")
    parser.add_argument("--list", action="store_true", help="List all pending inference tasks")
    parser.add_argument("--task", type=str, help="Process a specific task ID (Inference + Embeddings)")
    parser.add_argument("--infer-only", type=str, help="Run only Hermes inference for a specific task ID")
    parser.add_argument("--embed-only", type=str, help="Run only Vector Embedding for a specific Memory ID")
    
    args = parser.parse_args()
    
    home_dir = Path.home() / ".hermes" / "xibalba-cortex"
    store = GraphStore(home_dir)
    
    if args.list:
        tasks = store.list_inference_tasks(status="pending")
        print(f"\n--- {len(tasks)} Pending Tasks ---")
        for i, t in enumerate(tasks, 1):
            print(f"{i}. ID: {t['id']}")
            print(f"   Type: {t['task_type']} | Subject: {t['subject_type']} ({t['subject_id']})\n")
        return

    if args.embed_only:
        memory_id = args.embed_only
        try:
            mem = store.get_memory(memory_id)
            compute_embedding(store, memory_id, mem["content"])
        except KeyError:
            logger.error(f"Memory {memory_id} not found.")
        return
        
    target_task_id = args.task or args.infer_only
    if target_task_id:
        tasks = store.list_inference_tasks(status="pending")
        task = next((t for t in tasks if t["id"] == target_task_id), None)
        
        if not task:
            logger.error(f"Task {target_task_id} not found in pending queue.")
            return
            
        subject_id = task["subject_id"]
        subject_type = task["subject_type"]
        
        content, memory_id = get_content(store, subject_type, subject_id)
        if not content.strip():
            logger.error("No content found for task subject.")
            return
            
        logger.info(f"Processing Task: {target_task_id}")
        
        # Inference Step
        inference_result = run_hermes_inference(content)
        if inference_result:
            store.complete_inference_task(target_task_id, output_payload=inference_result, error=None)
            logger.info("✅ Inference completed and saved to graph store.")
            print(json.dumps(inference_result, indent=2))
        else:
            store.complete_inference_task(target_task_id, output_payload=None, error="Hermes inference failed")
            logger.error("❌ Inference failed.")

        # Embedding Step (Skip if --infer-only was used)
        if args.task and memory_id:
            compute_embedding(store, memory_id, content)
        
        return
        
    parser.print_help()

if __name__ == "__main__":
    main()
