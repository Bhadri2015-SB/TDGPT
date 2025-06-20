# run_chunking.py

from chunker import Chunker

INPUT_FILE = "C:\\Users\\bhadr\\Documents\\Troudz_poc\\TDGPT\\output\\MIPS_Assembly_Language_small_163.json"  # <-- path to your extracted JSON
OUTPUT_LOG_FIXED = "log_fixed_token.json"
OUTPUT_LOG_SLIDING = "log_sliding_window.json"
OUTPUT_LOG_SENTENCE = "log_sentence_merge.json"
OUTPUT_LOG_PARAGRAPH = "log_paragraph_split.json"
OUTPUT_LOG_RECURSIVE = "log_recursive_split.json"
OUTPUT_LOG_HYBRID = "log_hybrid_chunking.json"

if __name__ == "__main__":
    chunker = Chunker(INPUT_FILE)

    # Strategy 1: Fixed-token chunking
    # fixed_chunks = chunker.chunk_by_fixed_tokens(max_tokens=200)
    # chunker.log_chunking_result("fixed_token", fixed_chunks, OUTPUT_LOG_FIXED)

    # # Strategy 2: Sliding window chunking
    # sliding_chunks = chunker.chunk_by_sliding_window(max_tokens=200, stride=50)
    # chunker.log_chunking_result("sliding_window", sliding_chunks, OUTPUT_LOG_SLIDING)

    # # Strategy 3: Sentence Merge
    # sentence_chunks = chunker.chunk_by_sentence_merge(max_tokens=200)
    # chunker.log_chunking_result("sentence_merge", sentence_chunks, OUTPUT_LOG_SENTENCE)

    # # Strategy 4: Paragraph Split
    # paragraph_chunks = chunker.chunk_by_paragraph_split(max_tokens=200)
    # chunker.log_chunking_result("paragraph_split", paragraph_chunks, OUTPUT_LOG_PARAGRAPH)

    # # Strategy 5: Recursive Split
    # recursive_chunks = chunker.chunk_by_recursive_split(max_tokens=200)
    # chunker.log_chunking_result("recursive_split", recursive_chunks, OUTPUT_LOG_RECURSIVE)

    # ✅ Strategy 6: Hybrid Chunking
    hybrid_chunks = chunker.chunk_by_hybrid(max_tokens=200)
    chunker.log_chunking_result("hybrid", hybrid_chunks, OUTPUT_LOG_HYBRID)

    print(f"✅ Chunking complete. Logs saved to:")
    print(f"- {OUTPUT_LOG_FIXED}")
    print(f"- {OUTPUT_LOG_SLIDING}")
    print(f"- {OUTPUT_LOG_SENTENCE}")
    print(f"- {OUTPUT_LOG_PARAGRAPH}")
    print(f"- {OUTPUT_LOG_RECURSIVE}")
    print(f"- {OUTPUT_LOG_HYBRID}")
