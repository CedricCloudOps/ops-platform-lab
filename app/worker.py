import os, json, time
from kafka import KafkaConsumer

KAFKA_BROKER = os.environ.get("KAFKA_BROKER", "kafka:9092")

def main():
    for _ in range(40):
        try:
            consumer = KafkaConsumer(
                "document-events",
                bootstrap_servers=KAFKA_BROKER,
                auto_offset_reset="earliest",
                value_deserializer=lambda v: json.loads(v.decode()),
                group_id="worker",
            )
            print("Worker connected to Kafka, waiting for events...", flush=True)
            for msg in consumer:
                print("EVENT RECEIVED:", msg.value, flush=True)
            return
        except Exception as e:
            print("waiting for kafka...", e, flush=True); time.sleep(3)

if __name__ == "__main__":
    main()
