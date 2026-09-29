# 小规模规则选店原型

`competeai/examples/choice_demo.yaml` 使用四家餐厅、十位独立顾客和两轮模拟。基础画像从 `datasets/Dianping_Three_Source_Merged` 随机抽样并保存在 `competeai/examples/choice_demo_profiles.json`；模拟启动时不会扫描原始大文件。

每家模拟餐厅继承一个匿名历史基线：菜系、城市、人均消费、历史评论量和平均评分。历史评论量和评分参与平台推荐分数；顾客可见菜系、城市和人均消费。原始评论正文不加载到模拟中；顾客看到的评论和新增到店人数均由本次模拟生成。店名和菜单是虚构的，不对应原始商户。

十位顾客从至少有 5 条可关联历史评论的用户中抽样。每位顾客只保留历史评论数、最常评论餐厅的前三类菜系，以及历史消费参考；不保留用户 ID、昵称或评论正文。数据没有可靠年龄、收入、性别或人格字段，因此这些不再作为“真实画像”写入配置。顾客价格参考按历史人均消费初始化，之后与模拟中的实际点菜价格一起更新。新增的辣度偏好和表达风格不是源数据字段，而是明确标注的模拟假设，用于测试异质性。

抽样规则为固定随机种子 2026；餐厅要求至少 30 条评论，并优先抽到不同菜系。需要重新随机抽样时，在项目根目录运行 `python scripts/sample_choice_demo_profiles.py --seed 2027`，之后把新生成的画像文件与配置一起保存，确保实验可复现。

选店概率由顾客历史菜系偏好、餐厅评论数、最近三轮模拟到店人数、平均评分、该顾客在本次模拟中的重复到店次数、价格偏好和辣度偏好共同决定。每家餐厅有均匀探索下限，避免纯粹由声量和评分造成概率归零。每个顾客和轮次使用稳定种子抽样，`logs/<实验名>/choice_probabilities.jsonl` 保存概率、特征和实际选择。

到店体验与平台口碑分开生成：餐厅平均评分只作为较粗的长期基线，每次到店的食物、服务、环境和等待感受都加入独立且可复现的波动；辣度偏好会影响相关菜品体验和总体评分。评论提示词只收到当次体验结构化结果、所点菜品和顾客表达风格，不复述历史评论；0–4 分要求明确负面表达，且最终记录分数与模拟体验分一致。体验随机波动是待线下合作数据校准的研究假设，不是实测线下事实。

本示例使用 9100—9103 端口及四个独立 SQLite 文件，不会使用现有 9000/9001 实验数据库。

在项目根目录打开四个终端，分别启动数据库：

```powershell
Set-Location database/restaurant_sys
python manage.py migrate --settings=restaurant_sys.settings.choice_demo_1
python manage.py runserver 9100 --noreload --settings=restaurant_sys.settings.choice_demo_1
```

```powershell
Set-Location database/restaurant_sys
python manage.py migrate --settings=restaurant_sys.settings.choice_demo_2
python manage.py runserver 9101 --noreload --settings=restaurant_sys.settings.choice_demo_2
```

```powershell
Set-Location database/restaurant_sys
python manage.py migrate --settings=restaurant_sys.settings.choice_demo_3
python manage.py runserver 9102 --noreload --settings=restaurant_sys.settings.choice_demo_3
```

```powershell
Set-Location database/restaurant_sys
python manage.py migrate --settings=restaurant_sys.settings.choice_demo_4
python manage.py runserver 9103 --noreload --settings=restaurant_sys.settings.choice_demo_4
```

在第三个终端，从项目根目录运行：

```powershell
$env:OPENAI_KEY = (Get-Content ..\api.txt -Raw).Trim()
$env:OPENAI_BASE_URL = "https://api.ai-gaochao.cn/v1"
python run.py choice_demo --config competeai/examples/choice_demo.yaml
```

餐厅菜单中的菜品价格用于顾客价格历史。小规模配置为每位顾客提供了初始价格参考，之后按历次实际点选菜品的平均价格更新个人价格参考。
