import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app import load_config
from gemini_api_engine import GeminiApiEngine

async def test_live():
    cfg = load_config()
    print("Base URL:", cfg.get("ninerouter_url", "http://localhost:20128/v1"))
    print("Model:", cfg.get("ninerouter_model", "ag/gemini-3.8-flash-high"))
    engine = GeminiApiEngine(
        base_url=cfg.get("ninerouter_url", "http://localhost:20128/v1"),
        api_keys=[cfg.get("ninerouter_api_key")],
        default_model=cfg.get("ninerouter_model", "ag/gemini-3.8-flash-high"),
        timeout=60
    )
    
    pdf_path = r"downloads\the_warriors_ballad_1_2_en_14e8673b\episode_2\pdf\The_Warriors_Ballad_Tap_2.pdf"
    if os.path.exists(pdf_path):
        print(f"\n--- Testing with Real Comic PDF: {pdf_path} ---")
        pdf_prompt = (
            "Analyze this comic episode PDF. Return a valid JSON array of objects with 'page' (int) and 'speech' (string, narrative recap in English) for the first 5 pages.\n"
            "Format: [{\"page\": 1, \"speech\": \"...\"}, ...]"
        )
        t0 = time.time()
        res_pdf, model_pdf = await engine.generate_content(prompt=pdf_prompt, pdf_path=pdf_path)
        dur = time.time() - t0
        print(f"Time taken: {dur:.2f}s | Model used: {model_pdf}")
        print(f"Response preview:\n{res_pdf[:500]}")
    else:
        print("PDF file not found for test.")

if __name__ == "__main__":
    import time
    asyncio.run(test_live())
