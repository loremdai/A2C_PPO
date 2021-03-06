'''
created on Mar 12, 2018
@author: Shang-Yu Su (t-shsu)
'''
import torch
import torch.nn as nn
from torch.autograd import Variable
from torch.nn.utils import clip_grad_norm_
import torch.optim as optim
import numpy as np

########## 该文件为世界模型代码 ##########

use_cuda = torch.cuda.is_available()

class SimulatorModel(nn.Module):
    def __init__(
            self,
            agent_action_size,  # 智能体动作的数量
            hidden_size,    # 默认为80
            state_size,     # 状态s的维度，当前固定size为270
            user_action_size,   # 用户动作的数量
            reward_size=1,
            termination_size=1,     # 二元变量t的大小
            nn_type="MLP",  # 当前神经网络类别只实现了MLP
            discriminator=None
    ):
        super(SimulatorModel, self).__init__()

        self.agent_action_size = agent_action_size
        self.nn_type = nn_type
        self.D = discriminator
        state_size = 270

        if nn_type == "MLP":
            self.s_enc_layer = nn.Linear(state_size, hidden_size)   # state encoder
            # self.s_encode_layer=nn.Sequential(nn.Linear(state_size, hidden_size), nn.Softmax())
            self.a_enc_layer = nn.Linear(agent_action_size, hidden_size)    # action encoder
            # self.s_encode_layer=nn.Sequential(nn.Linear(agent_action_size, hidden_size), nn.Softmax())
            self.shared_layers = nn.Sequential(nn.Linear(hidden_size * 2, hidden_size), nn.Tanh())  # s&a concatenation

            self.s_next_pred_layer = nn.Linear(hidden_size, state_size)  # s_{t+1}
            self.r_pred_layer = nn.Linear(hidden_size, reward_size)  # reward, regression
            # 稍后的损失函数BCEWithLogitsLoss已经包括了sigmoid，因此此处省略
            self.t_pred_layer = nn.Sequential(nn.Linear(hidden_size, termination_size)) # term, classification
            # 稍后的损失函数CrossEntropyLoss已经包括了log_softmax，因此此处省略
            self.au_pred_layer = nn.Sequential(nn.Linear(hidden_size, user_action_size))  # user-action, classification

        # hyper parameters
        self.max_norm = 1   # 梯度裁剪参数
        lr = 0.001

        # optimizer & loss functions
        self.optimizer = optim.RMSprop(self.parameters(), lr=lr)

        self.CrossEntropyLoss = nn.CrossEntropyLoss()   # CrossEntropyLoss就是把Softmax–Log–NLLLoss合并成一步
        self.MSELoss = nn.MSELoss()
        self.BCEWithLogitsLoss = nn.BCEWithLogitsLoss() # BCEWithLogitsLoss就是把Sigmoid-BCELoss合成一步

        if use_cuda:
            self.cuda()

    def Variable(self, x):
        return Variable(x, requires_grad=False).cuda() if use_cuda else Variable(x, requires_grad=False)

    # ex: [[2], [3], [42]]
    def one_hot(self, int_list, num_digits):
        int_list = np.array(int_list).squeeze()
        one_hot_list = np.eye(num_digits)[int_list]
        return one_hot_list

    # 训练世界模型
    def train(self, s_t, a_t, s_tp1, r_t, t_t, ua_t):
        if self.nn_type == "MLP":   # [s_t, a_t, s_tp1,  r_t, t_t, ua_t]
            loss = 0
            s = self.Variable(torch.FloatTensor(s_t))
            a = self.Variable(torch.FloatTensor(self.one_hot(a_t, self.agent_action_size)))
            r = self.Variable(torch.FloatTensor(r_t))
            t = self.Variable(torch.FloatTensor(np.int32(t_t)))
            au = self.Variable(torch.LongTensor(np.squeeze(ua_t)))

            encoded_s = self.s_enc_layer(s)
            encoded_a = self.a_enc_layer(a)
            h = self.shared_layers(torch.cat((encoded_s, encoded_a), 1))
            r_pred = self.r_pred_layer(h)
            t_pred = self.t_pred_layer(h)
            au_pred = self.au_pred_layer(h)

            self.optimizer.zero_grad()

            loss = self.CrossEntropyLoss(au_pred, au) + self.MSELoss(r_pred, r) + self.BCEWithLogitsLoss(t_pred, t)
            loss.backward()
            clip_grad_norm_(self.parameters(), self.max_norm)
            self.optimizer.step()
            return loss

    # 用世界模型进行预测
    def predict(self, s, a):
        if self.nn_type == "MLP":
            s = self.Variable(torch.FloatTensor(s))
            a = self.Variable(torch.FloatTensor(self.one_hot(a, self.agent_action_size)))
            encoded_s = self.s_enc_layer(s)
            encoded_a = torch.unsqueeze(self.a_enc_layer(a), 0)
            h = self.shared_layers(torch.cat((encoded_s, encoded_a), 1))

            r_pred = self.r_pred_layer(h).cpu().data.numpy()
            t_pred = self.t_pred_layer(h).cpu().data.numpy()
            au_pred = torch.max(self.au_pred_layer(h), 1)[1].cpu().data.numpy()
            return au_pred, r_pred, t_pred

    def save_model(self, model_path):
        torch.save(self.state_dict(), model_path)
        print("model saved.")

    def load_model(self, model_path):
        self.load_state_dict(torch.load(model_path))
        print("model loaded.")