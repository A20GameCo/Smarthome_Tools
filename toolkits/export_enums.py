import json


def snake_to_camel_case(in_str: str) -> str:
    out_str = ""
    for part in in_str.split("_"):
        out_str += part.capitalize()
    return out_str


def gen_python_enums(data: dict, out_file: str):
    def gen_enum_to_str(enum_name: str, enum_data: dict, file):
        enum_type_name = snake_to_camel_case(enum_name)

        file.writelines([
            f'def {enum_name}_to_str(in_ident: {enum_type_name}) -> str:\n',
            '    """Translates a enum identifier to a string identifier"""\n',
            '    switcher = {\n'])

        index = 1
        for elem in enum_data:
            file.write(f'        {enum_type_name}.{elem}: "{elem}"{"," if index != len(enum_data) else ""}\n')
            index += 1

        file.writelines([
            '    }\n',
            f'    return switcher.get(in_ident, "{enum_data[0]}")\n'
        ])

    def gen_str_to_enum(enum_name: str, enum_data: dict, file):
        enum_type_name = snake_to_camel_case(enum_name)

        file.writelines([
            f'def str_to_{enum_name}(in_ident: str) -> {enum_type_name}:\n',
            '    """Translates a string identifier to a enum identifier"""\n',
            '    switcher = {\n'])

        index = 1
        for elem in enum_data:
            file.write(f'        "{elem}": {enum_type_name}.{elem}{"," if index != len(enum_data) else ""}\n')
            index += 1

        file.writelines([
            '    }\n',
            f'    return switcher.get(in_ident, {enum_type_name}.{enum_data[0]})\n'
        ])

    with open("../temp/" + out_file, 'w') as file:
        file.writelines(['"""Module containing the enums for gadgets"""\n',
                         'import enum\n'])

        for enum_name in data:
            file.write('\n\n')
            file.write(f'# region {enum_name.upper()}\n\n')
            enum_data = data[enum_name]
            file.write(f'class {snake_to_camel_case(enum_name)}(enum.IntEnum):\n')
            file.write(f'    """{enum_data["description"]}"""\n')
            index = 0
            for elem in enum_data["elements"]:
                file.write(f'    {elem} = {index}\n')
                index += 1
            file.write('\n\n')
            gen_enum_to_str(enum_name, enum_data["elements"], file)
            file.write('\n\n')
            gen_str_to_enum(enum_name, enum_data["elements"], file)
            file.write(f'\n# endregion\n')

        file.write('\n')


if __name__ == "__main__":
    with open('enum_data.json', 'r') as f:
        json_data = json.load(f)
        gen_python_enums(json_data["data"], "gadgetlib.py")