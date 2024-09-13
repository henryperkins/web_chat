import os
from pymongo import MongoClient
from bson import json_util
from datetime import datetime
from app import validation_schema, update_conversation_text

# Load environment variables
from dotenv import load_dotenv
load_dotenv()

# MongoDB connection
MONGODB_URI = os.getenv('MONGODB_URI')
mongo_client = MongoClient(MONGODB_URI)
db = mongo_client['chatbot_db']
conversations_collection = db['conversations']

# Create collection with validation
try:
    db.create_collection('conversations', validator=validation_schema)
    print("Collection 'conversations' created with schema validation.")
except Exception as e:
    if 'already exists' in str(e):
        db.command('collMod', 'conversations', validator=validation_schema)
        print("Collection 'conversations' already exists. Schema validation applied.")
    else:
        print(f"An error occurred: {e}")

# Create indexes
conversations_collection.create_index(
    [('conversation_text', 'text')],
    name='conversation_text_index',
    default_language='english'
)

conversations_collection.create_index(
    [('conversation_id', 1), ('user_id', 1)],
    name='conversation_user_idx',
    unique=True
)

conversations_collection.create_index(
    [('created_at', -1)],
    name='created_at_idx'
)

print("Indexes created successfully.")
