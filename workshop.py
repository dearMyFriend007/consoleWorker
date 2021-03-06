# coding=UTF-8
import csv
import importlib
import logging
import logging.config
import queue

import threading
import time
import traceback

from GlobalVar import cf
from BasicRobot import BasicRobot
from beanBuilder.ProjectBeanBuilder import beanBuilder
from webWorker.report.ReportModel import Customer, BuildingProject, Report


class WorkShop:
    """工作间类
       主要使用的是controller、daTask两个方法，主持多线程操作
       初始化需要指定员工类的全路径名（如报备类工作间为：baobeiWorkerPackage）
    """

    def __init__(self):
        self.doneItems = []

    def addDoneItem(self, itemNo):
        # 当队列满时按设置移除之前的单号
        if len(self.doneItems) > cf.getint('workShop', 'maxQueue'):
            # 移除队列前部的指定数量的单号
            self.doneItems = self.doneItems[cf.getint('workShop', 'popNum'):]
        self.doneItems.append(itemNo)
        if logging.root.isEnabledFor(logging.DEBUG):
            logging.debug(f'doneItems(%s)' % self.doneItems)

    def isDoneItem(self, itemNo):
        return itemNo in self.doneItems

    def work(self, excel_data):
        if logging.root.isEnabledFor(logging.DEBUG):
            logging.debug(f"workItem[%s] is on process" % excel_data)

        itemNo = excel_data[0]
        channelNo = excel_data[1]
        report = Report(itemNo, channelNo)

        userId = excel_data[2]
        userName = excel_data[3]
        tel = excel_data[4]
        sex = excel_data[5]
        desc = excel_data[6]
        customer = Customer(userId, tel, userName, sex)
        customer.setDesc(desc)

        projectId = excel_data[7]
        projectName = excel_data[8]
        project = BuildingProject(projectId, projectName)

        report.setCustomer(customer)
        report.setProject(project)

        # 根据渠道ID来获取配置中指定的员工编号
        workerNo = cf.get('api', channelNo)

        if workerNo is None:
            logging.debug("channel(%s) map any worker!" % channelNo)

        bean = beanBuilder.getBeanByWorkerNo(workerNo)

        if bean is None:
            logging.debug("worker(%s) 没有配置对应的SOP操作！" % workerNo)

        #  todo 这里需要把调用的worker改成单例模式，不需要每次都进行实例化，使用时只需要每次初始化worker的参数即可
        workerModuleObj = importlib.import_module('.' + bean.moduleName, bean.modulePackage)
        workerObj = getattr(workerModuleObj, bean.moduleName)
        worker = workerObj()
        worker.setReport(report)

        robot = BasicRobot(worker)
        if logging.root.isEnabledFor(logging.DEBUG):
            logging.debug("worker({0}) is process the report({1})".format(robot.getWorkerNo(), itemNo))
        try:
            robot.doJob()
            worker.handleCvs(itemNo, '操作完成')
        except Exception as e:
            logging.error("worker({0}) handle report({1}) failed".format(robot.getWorkerNo(), itemNo))
            logging.error("error mess:%s" % traceback.format_exc())
            worker.handleCvs(itemNo, 'failed')

    def doTask(self, itemQueue):
        """
        工作台方法（消费者），工作者从此处获得操作单来进行work操作
        :param itemQueue: 操作单队列
        :return: None
        """
        while 1:
            if itemQueue.empty():
                time.sleep(int(cf.get('workShop','worker_work_freq')))
            self.work(itemQueue.get())  # 若队列中有待处理的单则取出处理

    def controller(self, itemQueue):
        """
        监工方法（生产者），负责获得操作单并放入操作单队列
        :param itemQueue: 操作单队列
        :return: None
        """
        while 1:
            if itemQueue.empty():
                if logging.root.isEnabledFor(logging.DEBUG):
                    logging.debug(f"读取文件获取执行任务")
                # todo 这里取操作单的操作应从数据库中获取
                with open('export/customer.csv', 'r', encoding='utf-8') as csvfile:
                    csv_reader = csv.reader(csvfile)
                    for excel_data in csv_reader:
                        if len(excel_data) <= 0:
                            continue
                        itemNo = excel_data[0]
                        if self.isDoneItem(itemNo):  # 判断该单据是否处理过
                            continue
                        self.addDoneItem(itemNo)  # 将需要处理的单号置为已处理 #todo 这里需要考虑操作失败时的策略
                        itemQueue.put(excel_data)  # 将需要处理的单号丢进队列里
                time.sleep(int(cf.get('workShop','controller_work_freq')))


def initWorkShop(workerNum=0):
    """
    初始化工作间
    :param workerNum: 工作间工作者数量
    :return: None
    """
    # 初始化日志配置
    # logging.config.fileConfig('conf/logging.conf')
    # 配置工作间工种
    workerShop = WorkShop()
    itemQueue = queue.Queue()
    threads = []
    # 创建监工线程
    wokerThread = threading.Thread(name='workShop(controller)', target=WorkShop.controller,
                                   args=(workerShop, itemQueue,))
    wokerThread.start()
    if workerNum <= 0:  # 若初始化工作者人数为负数或为空则从配置中获得
        workerNum = cf.getint('workShop', 'workerNum')

    # 按配置开起工作者子线程
    for i in range(0, workerNum):
        t = threading.Thread(name='workShop(No%s_worker)' % i, target=WorkShop.doTask,
                             args=(workerShop, itemQueue,))
        t.start()
        threads.append(t)

    for t in threads:
        t.join()


if __name__ == '__main__':
    initWorkShop()
