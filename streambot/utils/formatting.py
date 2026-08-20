def humanbytes(size):
    if not size:
        return ""
    power = 2 ** 10
    n = 0
    labels = {0: " ", 1: "Ki", 2: "Mi", 3: "Gi", 4: "Ti"}
    while size > power:
        size /= power
        n += 1
    return f"{round(size, 2)} {labels[n]}B"


def get_readable_time(seconds: int) -> str:
    count = 0
    parts = []
    suffixes = ["s", "m", "h", " days"]
    while count < 4:
        count += 1
        if count < 3:
            remainder, result = divmod(seconds, 60)
        else:
            remainder, result = divmod(seconds, 24)
        if seconds == 0 and remainder == 0:
            break
        parts.append(int(result))
        seconds = int(remainder)
    parts = [f"{p}{suffixes[i]}" for i, p in enumerate(parts)]
    readable = ""
    if len(parts) == 4:
        readable += parts.pop() + ", "
    parts.reverse()
    readable += ": ".join(parts)
    return readable
