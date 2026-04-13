from indexer import get_parser
from rich import print

def print_node(node, level=0):
    val = ""
    if node.type == 'identifier':
        val = " (id)"
    print('  '*level + str(node.type) + val)
    for c in node.children:
        print_node(c, level+1)

def main():
    file_path = r"C:\Users\fulld\Desktop\SE2_Wangzhou_Order-feat-order-track\src\main\java\fit\se2\group21\wangzhou_order\service\AuthService.java"
    with open(file_path, "r", encoding="utf-8") as f:
        content = f.read()
    tree = get_parser().parse(bytes(content, 'utf-8'))
    
    for child in tree.root_node.children:
        if child.type == 'class_declaration':
            print_node(child)
            break

if __name__ == "__main__":
    main()
