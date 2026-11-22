from io import BytesIO


def as_bytes(doc):
    buffer = BytesIO()
    doc.save(buffer)
    return buffer.getvalue()
