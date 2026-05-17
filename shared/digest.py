def build_digest_text(
    package_name: str, date_str: str, total_count: int, topics: list[dict]
) -> str:
    """Compose the digest message shown in Telegram.

    Args:
        package_name: Package name displayed in the header.
        date_str: ISO-8601 date string for the digest date.
        total_count: Total number of reviews analyzed.
        topics: List of topic summary dictionaries.

    Returns:
        Formatted multiline digest message.
    """
    lines = [
        f"📊 Daily review digest — {package_name}",
        f"Date: {date_str}  |  Reviews analysed: {total_count}",
        "",
        f"{len(topics)} complaint topics found:",
        "",
    ]

    for index, topic in enumerate(topics, start=1):
        lines.append(
            f"{index}. {topic.get('topic', 'Unknown Topic')} — {topic.get('count', 0)} reviews"
        )

    lines.extend(["", 'Reply /topic "<TopicName>" 1-10 to read reviews.'])
    return "\n".join(lines)
