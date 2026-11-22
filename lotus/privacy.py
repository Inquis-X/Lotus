from lotus.settings import ROOT, read_yaml


def filter_posts(posts, declared_pages, report_year):
    allowed, excluded = [], []
    config = read_yaml(ROOT / "config/extraction.yaml")
    for post in posts:
        reasons = []
        if post.mentions_minor:
            reasons.append("Упоминание несовершеннолетнего")
        if post.mentions_third_party:
            reasons.append("Сведения о третьем лице")
        if post.official_duties:
            reasons.append("Должностные обязанности")
        if post.published.year != report_year:
            reasons.append("Вне отчётного года")
        if post.page_url not in declared_pages:
            reasons.append("Страница отсутствует в заявленных")
        if any(word in post.text.casefold() for word in config["special_categories"]):
            reasons.append("Специальная категория сведений")
        if reasons:
            excluded.append({"post_id": post.id, "reasons": reasons})
        else:
            allowed.append(post)
    return allowed, excluded
