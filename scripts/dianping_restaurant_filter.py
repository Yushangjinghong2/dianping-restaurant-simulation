POSITIVE = (
    "菜", "餐", "火锅", "烧烤", "小吃", "面馆", "粉面", "料理", "海鲜", "自助",
    "食堂", "饭店", "酒楼", "农家", "烤鸭", "烤鱼", "龙虾", "寿司", "披萨",
    "比萨", "汉堡", "牛排", "粥", "麻辣烫", "香锅", "包子", "饺子", "馄饨",
    "米线", "快餐", "简餐", "豆浆", "早餐",
)

NEGATIVE = (
    "超市", "便利店", "食品茶酒", "食品保健", "零食", "烟酒", "茶叶", "水果",
    "生鲜", "菜市场", "粮油", "特产", "购物", "商场", "百货", "婚庆", "小商品",
    "KTV", "电影院", "景点", "博物馆", "休闲娱乐", "美容", "美发", "酒店住宿",
)

DRINK_DESSERT_STYLES = (
    "咖啡", "茶馆", "甜品", "饮品", "饮料", "面包", "西点", "蛋糕", "冰淇淋",
    "奶茶", "酒吧", "果汁", "糖水", "巧克力",
)


def is_restaurant(style, tags=""):
    style = str(style or "").strip()
    tags = str(tags or "").strip()
    combined = f"{style}|{tags}"
    if any(word.lower() in combined.lower() for word in NEGATIVE):
        return False
    if any(word.lower() in style.lower() for word in DRINK_DESSERT_STYLES):
        return False
    return any(word in style for word in POSITIVE)


def is_stanford_restaurant(shop):
    category = str(shop.get("category", "")).strip()
    breadcrumb = str(shop.get("breadcrumb", "")).strip()
    if any(word.lower() in category.lower() for word in DRINK_DESSERT_STYLES):
        return False
    if any(word.lower() in f"{category}|{breadcrumb}".lower() for word in NEGATIVE):
        return False
    return True
