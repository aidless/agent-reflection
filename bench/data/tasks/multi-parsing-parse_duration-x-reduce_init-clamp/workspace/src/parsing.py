def parse_duration(text):
    total = 0
    num = ""
    for ch in text:
        if ch.isdigit():
            num += ch
        else:
            if num:
                n = int(num)
                if ch == "h":
                    total += n * 3600
                elif ch == "m":
                    total += n
                elif ch == "s":
                    total += n
                num = ""
    return total if num == "" else total + int(num)
