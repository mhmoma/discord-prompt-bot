# -*- coding: utf-8 -*-
import sys
import os

# 添加当前目录到路径
current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, current_dir)
os.chdir(current_dir)

# 导入并运行转换函数
from convert_lexicon import convert_lexicon_to_knowledge_base
convert_lexicon_to_knowledge_base()



