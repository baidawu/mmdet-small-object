from torch.utils.data import Dataset
import os
import torch
import json
from PIL import Image
from sklearn import preprocessing
# from lxml import etree
from lxml import html
etree = html.etree


class MyDataSet(Dataset):
    """读取解析PASCAL VOC2007/2012数据集"""

    def __init__(self, voc_root, year="2012", transforms=None, txt_name: str = "train.txt"):
        assert year in ["2007", "2012"], "year must be in ['2007', '2012']"
        # self.root = os.path.join(voc_root, "VOCdevkit", f"VOC{year}")
        self.root = os.path.join(voc_root, "Pest24")
        self.img_root = os.path.join(self.root, "JPEGImages")  # 图片路径
        self.annotations_root = os.path.join(self.root, "Annotations")  # XML文件路径

        # read train.txt or val.txt file
        txt_path = os.path.join(self.root, "ImageSets", txt_name)  # train.txt文件路径，文件里是分割好的训练集图片名称
        assert os.path.exists(txt_path), "not found {} file.".format(txt_name)

        with open(txt_path) as read:
            self.xml_list = [os.path.join(self.annotations_root, line.strip() + ".xml")
                             for line in read.readlines() if len(line.strip()) > 0]  # xml_list存储所有xml文件路径

        # check file
        assert len(self.xml_list) > 0, "in '{}' file does not find any information.".format(txt_path)
        for xml_path in self.xml_list:
            assert os.path.exists(xml_path), "not found '{}' file.".format(xml_path)

        # read class_indict 解析json文件
        # json_file = './pascal_voc_classes.json'
        # assert os.path.exists(json_file), "{} file not exist.".format(json_file)
        # json_file = open(json_file, 'r')
        # self.class_dict = json.load(json_file)  # class_dict存储所有类别名称和index：index：value
        # json_file.close()

        self.transforms = transforms  # 根据传入的transform预处理方法，进行图片预处理

    def __len__(self):
        return len(self.xml_list)

    def __getitem__(self, idx):
        # read xml
        xml_path = self.xml_list[idx]
        with open(xml_path, encoding='utf-8') as fid:
            xml_str = fid.read()
        xml = etree.fromstring(xml_str.encode('utf-8'))
        data = self.parse_xml_to_dict(xml)["annotation"]  # 读取的标注数据

        img_path = os.path.join(self.img_root, "{0}.jpg".format(data["filename"]))
        image = Image.open(img_path)
        if image.format != "JPEG":
            raise ValueError("Image '{}' format not JPEG".format(img_path))

        boxes = []
        labels = []
        iscrowd = []
        assert "object" in data, "{} lack of object information.".format(xml_path)
        for obj in data["object"]:
            xmin = float(obj["bndbox"]["xmin"])
            xmax = float(obj["bndbox"]["xmax"])
            ymin = float(obj["bndbox"]["ymin"])
            ymax = float(obj["bndbox"]["ymax"])

            # 进一步检查数据，有的标注信息中可能有w或h为0的情况，这样的数据会导致计算回归loss为nan
            if xmax <= xmin or ymax <= ymin:
                print("Warning: in '{}' xml, there are some bbox w/h <=0".format(xml_path))
                continue

            boxes.append([xmin, ymin, xmax, ymax])
            # labels.append(self.class_dict[obj["name"]]) # 这里的name是目标的类别1 2 3 4等
            labels.append(int(obj["name"]))  # xml文件中的obj["name"]即为类别1，2，3，4；直接用其作为label
            if "difficult" in obj:
                iscrowd.append(int(obj["difficult"]))
            else:
                iscrowd.append(0)

        # convert everything into a torch.Tensor
        # labels = int(labels) # labels强制转换类型
        # print(labels)
        boxes = torch.as_tensor(boxes, dtype=torch.float32)
        # labels = torch.as_tensor(labels, dtype=torch.int64) # 原文中labels列表是类别 1 2 3 4列表，现在是名称 a b c列表
        """
        from sklearn import preprocessing
        import torch
        labels = ['cat', 'dog', 'mouse', 'elephant', 'pandas']
        le = preprocessing.LabelEncoder()
        targets = le.fit_transform(labels)
        # targets: array([0, 1, 2, 3])
        targets = torch.as_tensor(targets)
        # targets: tensor([0, 1, 2, 3])
        """
        # le = preprocessing.LabelEncoder()
        # targets = le.fit_transform(labels)
        # labels = torch.as_tensor(targets)   # 将字符串列表转换为张量
        labels = torch.as_tensor(labels, dtype=torch.int64)

        iscrowd = torch.as_tensor(iscrowd, dtype=torch.int64)
        image_id = torch.tensor([idx])
        area = (boxes[:, 3] - boxes[:, 1]) * (boxes[:, 2] - boxes[:, 0])  # 面积

        target = {}
        target["boxes"] = boxes
        target["labels"] = labels  # target[label]为类别1，2，3，4
        target["image_id"] = image_id
        target["area"] = area
        target["iscrowd"] = iscrowd

        if self.transforms is not None:
            image, target = self.transforms(image, target)

        return image, target

    def get_height_and_width(self, idx):  # 图片的高度和宽度
        # read xml
        xml_path = self.xml_list[idx]
        with open(xml_path, encoding='utf-8') as fid:
            xml_str = fid.read()
        # xml = etree.fromstring(xml_str)
        xml = etree.fromstring(xml_str.encode('utf-8'))
        data = self.parse_xml_to_dict(xml)["annotation"]
        data_height = int(data["size"]["height"])
        data_width = int(data["size"]["width"])
        return data_height, data_width

    def parse_xml_to_dict(self, xml):
        """
        将xml文件解析成字典形式，参考tensorflow的recursive_parse_xml_to_dict
        Args:
            xml: xml tree obtained by parsing XML file contents using lxml.etree
        Returns:
            Python dictionary holding XML contents.
        """

        if len(xml) == 0:  # 遍历到底层，直接返回tag对应的信息
            return {xml.tag: xml.text}

        result = {}
        for child in xml:
            child_result = self.parse_xml_to_dict(child)  # 递归遍历标签信息
            if child.tag != 'object':
                result[child.tag] = child_result[child.tag]
            else:
                if child.tag not in result:  # 因为object可能有多个，所以需要放入列表里
                    result[child.tag] = []
                result[child.tag].append(child_result[child.tag])
        return {xml.tag: result}

    def coco_index(self, idx):
        """
        该方法是专门为pycocotools统计标签信息准备，不对图像和标签作任何处理
        由于不用去读取图片，可大幅缩减统计时间
        Args:
            idx: 输入需要获取图像的索引
        """
        # read xml
        xml_path = self.xml_list[idx]
        with open(xml_path, encoding='utf-8') as fid:
            xml_str = fid.read()
        xml = etree.fromstring(xml_str.encode('utf-8'))
        data = self.parse_xml_to_dict(xml)["annotation"]
        data_height = int(data["size"]["height"])
        data_width = int(data["size"]["width"])
        # img_path = os.path.join(self.img_root, data["filename"])
        # image = Image.open(img_path)
        # if image.format != "JPEG":
        #     raise ValueError("Image format not JPEG")
        boxes = []
        labels = []  # labels存储的是类别的索引值1，2，3，4，而并非类别本身
        iscrowd = []  # 若iscrowd为0，则表示为单目标，较好检测
        for obj in data["object"]:
            xmin = float(obj["bndbox"]["xmin"])
            xmax = float(obj["bndbox"]["xmax"])
            ymin = float(obj["bndbox"]["ymin"])
            ymax = float(obj["bndbox"]["ymax"])
            boxes.append([xmin, ymin, xmax, ymax])

            # labels.append(self.class_dict[obj["name"]])
            labels.append(int(obj["name"]))
            iscrowd.append(int(obj["difficult"]))

        # convert everything into a torch.Tensor
        boxes = torch.as_tensor(boxes, dtype=torch.float32)
        # le = preprocessing.LabelEncoder()
        # targets = le.fit_transform(labels)
        # labels = torch.as_tensor(targets)  # 将字符串列表转换为张量
        labels = torch.as_tensor(labels, dtype=torch.int64)

        iscrowd = torch.as_tensor(iscrowd, dtype=torch.int64)
        image_id = torch.tensor([idx])  # idx当前数据对应的索引值
        area = (boxes[:, 3] - boxes[:, 1]) * (boxes[:, 2] - boxes[:, 0])  # 面积

        target = {}
        target["boxes"] = boxes
        target["labels"] = labels
        target["image_id"] = image_id
        target["area"] = area
        target["iscrowd"] = iscrowd

        return (data_height, data_width), target

    @staticmethod
    def collate_fn(batch):
        return tuple(zip(*batch))