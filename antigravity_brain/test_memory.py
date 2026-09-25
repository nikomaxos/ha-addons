import os
import sqlite3
import memory_manager

API_KEY = "YOUR_API_KEY_HERE"

# Clean DB if exists for testing
if os.path.exists("memory.db"):
    os.remove("memory.db")

memory_manager.init_db()

res = memory_manager.store_memory("My favorite color is bright blue.", API_KEY)
print("Store:", res)

res2 = memory_manager.store_memory("I allergic to peanuts.", API_KEY)
print("Store2:", res2)

print("\n--- Search 1 ---")
search_res = memory_manager.search_memories("What color should I paint my car?", API_KEY)
print(search_res)

print("\n--- Search 2 ---")
search_res2 = memory_manager.search_memories("Can I eat this peanut butter jelly sandwich?", API_KEY)
print(search_res2)

print("\n--- Search 3 ---")
search_res3 = memory_manager.search_memories("How do you fix a computer?", API_KEY)
print(search_res3)

