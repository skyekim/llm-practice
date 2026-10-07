from sentence_transformers import SentenceTransformer, util

model = SentenceTransformer("all-MiniLM-L6-v2")
a, b, c = model.encode(["remote work", "work from home", "studying computer science"])
print(util.cos_sim(a, b), util.cos_sim(a, c))