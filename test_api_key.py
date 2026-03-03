
import anthropic
import sys

api_key = input("Enter your Anthropic API key: ").strip()

client = anthropic.Anthropic(api_key=api_key)

print("\nTesting API key...")

try:
    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=64,
        messages=[{"role": "user", "content": "Reply with API key is working!"}],
    )
    print(f"✅ Success! Response: {message.content[0].text}")
except anthropic.AuthenticationError:
    print("❌ Invalid API key.")
    sys.exit(1)
except anthropic.PermissionDeniedError:
    print("❌ API key lacks permission.")
    sys.exit(1)
except Exception as e:
    print(f"❌ Unexpected error: {e}")
    sys.exit(1)

