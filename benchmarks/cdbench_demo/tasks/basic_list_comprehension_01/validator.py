#!/usr/bin/env python3
import json
import sys

def validate(answer_path: str) -> float:
    """Validate if the agent chose the correct answer."""
    try:
        with open(answer_path) as f:
            data = json.load(f)
        
        choice = data.get('choice', '').strip().upper()
        correct = 'A'
        
        if choice == correct:
            return 1.0
        return 0.0
    except Exception as e:
        print(f"Validation error: {e}", file=sys.stderr)
        return 0.0

if __name__ == '__main__':
    score = validate('/work/answer.json')
    print(f"Score: {score}")
    sys.exit(0 if score == 1.0 else 1)
