from re import I
from sys import meta_path
import torch
import random
import numpy as np
from torch import load, sigmoid, cat, rand, bmm, mean, matmul, stack
from torch.nn import *
from torch.optim import Adam
from torch.nn.init import uniform_
from MCRec import MCRec
import pickle

gpu_id = 0
latent_dim = 128
att_size = 128
layer_size = [512, 256, 128, 64]
eval_processes_num = 4
negative_num = 1

with open('user_dict.txt', 'rb') as f:
    data = f.read()
    user_dict = pickle.loads(data)

with open('item_dict.txt', 'rb') as f:
    data = f.read()
    item_dict = pickle.loads(data)
# user_dict = np.load('user_dict.npy', allow_pickle='TRUE')
# item_dict = np.load('item_dict.npy', allow_pickle='TRUE')
user_dict_r=dict([val,key] for key,val in user_dict.items())
item_dict_r=dict([val,key] for key,val in item_dict.items())


class BPR(Module):
    def __init__(self, user_set, item_set, hidden_dim=512):
        super(BPR, self).__init__()
        self.hidden_dim = hidden_dim
       
        self.user_gama = Embedding(len(user_set), self.hidden_dim)
        self.item_gama = Embedding(len(item_set), self.hidden_dim)
        self.user_beta = Embedding(len(user_set), 1)
        self.item_beta = Embedding(len(item_set), 1)

        self.user_set = list(user_set)
        self.item_set = list(item_set)
        
        init.uniform_(self.user_gama.weight, 0, 0.01)
        init.uniform_(self.user_beta.weight, 0, 0.01)
        init.uniform_(self.item_gama.weight, 0, 0.01)
        init.uniform_(self.item_beta.weight, 0, 0.01)
        
        self.user_idx = {user:_index for _index, user in enumerate(user_set)}
        self.item_idx = {item:_index for _index, item in enumerate(item_set)}

    def get_user_idx(self, users):
        if self.user_beta.weight.is_cuda:
            return torch.tensor([self.user_idx[user] for user in users]) \
                .long() \
                .cuda(self.user_beta.weight.get_device())
        else:
            return torch.tensor([self.user_idx[user] for user in users]) \
                .long()
    def get_item_idx(self, items):
        if self.user_beta.weight.is_cuda:
            return torch.tensor([self.item_idx[item] for item in items]) \
                .long() \
                .cuda(self.user_beta.weight.get_device())
        else:
            return torch.tensor([self.item_idx[item] for item in items]) \
                .long()
    def get_user_gama(self, users):
        return self.user_gama(self.get_user_idx(users))
    def get_item_gama(self, items):
        return self.item_gama(self.get_item_idx(items))
    def forward(self, users, items):
        batchsize = len(users)
        user_gama = self.get_user_gama(users)
        user_beta = self.user_beta(self.get_user_idx(users))
        item_gama = self.get_item_gama(items)
        item_beta = self.item_beta(self.get_item_idx(items))
        return item_beta.view(batchsize) + user_beta.view(batchsize) \
            + bmm(user_gama.view(batchsize, 1, self.hidden_dim), 
                item_gama.view(batchsize, self.hidden_dim, 1)).view(batchsize)

    def fit(self, users, items, p=2):
        batchsize = len(users)
        user_gama = self.get_user_gama(users)
        user_beta = self.user_beta(self.get_user_idx(users))
        item_gama = self.get_item_gama(items)
        item_beta = self.item_beta(self.get_item_idx(items))
        return item_beta.view(batchsize) + user_beta.view(batchsize) \
            + bmm(user_gama.view(batchsize, 1, self.hidden_dim),
                item_gama.view(batchsize, self.hidden_dim, 1)).view(batchsize), \
            user_gama.norm(p=p)+ item_beta.norm(p=p)+ user_beta.norm(p=p)+item_gama.norm(p=p)

class VTBPR(BPR):
    def __init__(self, user_set, item_set,metapath_feature,metapath_list_attributes, hidden_dim=512,
        theta_text = True, theta_visual = True):
        super(VTBPR, self).__init__(user_set, item_set, hidden_dim=hidden_dim)

        self.theta_user_visual = Embedding(len(user_set), self.hidden_dim)
        self.theta_user_text = Embedding(len(user_set), self.hidden_dim)
        # metapath_list[i]: (metapath_file, path_dict, path_num, hop_num,max_user_id, max_item_id,id2type) 
        #initiate MCRec
        # arow = len(metapath_feature)
        # acol = len(metapath_feature[0])
        # print("Rows : " + str(arow))
        # print("Columns : " + str(acol))
        self.metapath_feature = metapath_feature
        self.metapath_list_attributes=metapath_list_attributes[0]
        metapath_list_attributes = []
        
        for i in range(len(self.metapath_feature)):
            metapath_list_attributes.append((self.metapath_list_attributes[0], self.metapath_list_attributes[1]))
        global MCRec
        self.mcrec = MCRec(latent_dim=latent_dim, att_size=att_size, feature_size=self.hidden_dim,
                  negative_num=negative_num,
                  user_num=self.metapath_feature[0][4], item_num=self.metapath_feature[0][5],
                  metapath_list_attributes=metapath_list_attributes,
                  layer_size=layer_size)

        self.path_dict = self.metapath_feature[0][1]
        self.id2type = self.metapath_feature[0][6]
        self.user_num = self.metapath_feature[0][4]
        self.item_num= self.metapath_feature[0][5]
        self.negative_num = 1
        init.uniform_(self.theta_user_text.weight, 0, 0.01)
        init.uniform_(self.theta_user_visual.weight, 0, 0.01)

    def get_theta_user_visual(self, users):
        return self.theta_user_visual(self.get_user_idx(users))

    def get_theta_user_text(self, users):
        return self.theta_user_text(self.get_user_idx(users))

    def forward(self, users, items, visual_features, textural_features):
        batchsize = len(users)
        bpr = BPR.forward(self, users, items)
        theta_user_visual = self.get_theta_user_visual(users)
        theta_user_text = self.get_theta_user_text(users)
        userss = users
        metapath_input_list= [ ]
        for idx in range(batchsize): #這裡的迴圈數要和batch數一樣
            #self.negative_num+1  試試看要不要+1
            k = self.negative_num-1
            metapath_input = np.zeros((self.negative_num , self.metapath_list_attributes[0], self.metapath_list_attributes[1], self.hidden_dim), dtype=np.float32) 
            metapath_input_list.append(metapath_input)
            u= user_dict[int(userss[idx])]
            i= item_dict[int(items[idx])]
            u, i = int(u), int(i)
            if (u, i) in self.path_dict:
                for p_i in range(len(self.path_dict[(u, i)])): #每個path
                    for p_j in range(len(self.path_dict[(u, i)][p_i])): #裡的每個node
                        type_id = self.path_dict[(u, i)][p_i][p_j][0]
                        node_type = self.id2type[type_id]
                        if  node_type == 'u':
                            
                            metapath_input_list[idx][k][p_i][p_j] = self.get_user_gama([str(user_dict_r[u])]).cpu().detach().numpy()
                        elif node_type == ('t'or'b') :
                              
                            metapath_input_list[idx][k][p_i][p_j] = self.get_item_gama([str(item_dict_r[i])]).cpu().detach().numpy()
        
            # metapath_input_list.append(metapath_input)
        
        #user, item, metapath index 系統轉換
        user_input  = np.array([user_dict[int(user)] for user in userss])
        item_input = np.array([item_dict[int(item)] for item in items])       
        metapath_inputs = [metapath_input_list]
        
        mcrec = MCRec.forward(self.mcrec, user_input, item_input, metapath_inputs)
        return bpr \
            + bmm(theta_user_visual.view(batchsize, 1, self.hidden_dim), 
                visual_features.view(batchsize, self.hidden_dim , 1)).view(batchsize) \
            + bmm(theta_user_text.view(batchsize, 1, self.hidden_dim), 
                textural_features.view(batchsize, self.hidden_dim, 1 )).view(batchsize) \
            + mcrec
         
    def fit(self, users, items, visual_features, textural_features):
        batchsize = len(users)
        bpr, bprweight = BPR.fit(self, users, items)

        theta_user_visual = self.get_theta_user_visual(users)
        theta_user_text = self.get_theta_user_text(users)
        userss = users
        metapath_input_list= [ ]
        for idx in range(batchsize): #這裡的迴圈數要和batch數一樣
            #self.negative_num+1  原本有+1
            k = self.negative_num-1
            metapath_input = np.zeros((self.negative_num , self.metapath_list_attributes[0], self.metapath_list_attributes[1], self.hidden_dim), dtype=np.float32) 
            metapath_input_list.append(metapath_input)
            u= user_dict[int(userss[idx])]
            i= item_dict[int(items[idx])]
            u, i = int(u), int(i)
            if (u, i) in self.path_dict:
                for p_i in range(len(self.path_dict[(u, i)])): #每個path
                    for p_j in range(len(self.path_dict[(u, i)][p_i])): #裡的每個node
                        type_id = self.path_dict[(u, i)][p_i][p_j][0]
                        node_type = self.id2type[type_id]
                        if  node_type == 'u':
                            
                            metapath_input_list[idx][k][p_i][p_j] = self.get_user_gama([str(user_dict_r[u])]).cpu().detach().numpy()
                        elif node_type == ('t'or'b') :
                              
                            metapath_input_list[idx][k][p_i][p_j] = self.get_item_gama([str(item_dict_r[i])]).cpu().detach().numpy()
        
            # metapath_input_list.append(metapath_input)
        # print('metalist shape:',np.array(metapath_input_list).shape)
        #user, item, metapath index 系統轉換
        user_input  = np.array([user_dict[int(user)] for user in userss])
        item_input = np.array([item_dict[int(item)] for item in items])       
        metapath_inputs = [metapath_input_list]
        # print('user:',user_input, 'item:',item_input)
        mcrec = MCRec.forward(self.mcrec, user_input, item_input, metapath_inputs)
        
        return bpr \
            + bmm(theta_user_visual.view(batchsize, 1, self.hidden_dim), 
                visual_features.view(batchsize, self.hidden_dim , 1)).view(batchsize) \
            + bmm(theta_user_text.view(batchsize, 1, self.hidden_dim), 
                textural_features.view(batchsize, self.hidden_dim, 1 )).view(batchsize) \
            + mcrec, \
            bprweight + self.get_theta_user_text(set(users)).norm(p=2) + self.get_theta_user_visual(set(users)).norm(p=2) + mcrec.norm(p=2)

class TextCNN(Module):
    def __init__(self, sentence_size = (83, 300), output_size = 512, uniform=False):
        super(TextCNN, self).__init__()
        self.max_sentense_length, self.word_vector_size = sentence_size
        self.text_cnn = ModuleList([Sequential(
            Conv2d(in_channels=1,out_channels=100,kernel_size=(2,self.word_vector_size),stride=1),
            Sigmoid(),
            MaxPool2d(kernel_size=(self.max_sentense_length - 1,1),stride=1)
        ), Sequential(
            Conv2d(in_channels=1,out_channels=100,kernel_size=(3,self.word_vector_size),stride=1),
            Sigmoid(),
            MaxPool2d(kernel_size=(self.max_sentense_length - 2,1),stride=1)
        ), Sequential(
            Conv2d(in_channels=1,out_channels=100,kernel_size=(4,self.word_vector_size),stride=1),
            Sigmoid(),
            MaxPool2d(kernel_size=(self.max_sentense_length - 3,1),stride=1)
        ), Sequential(
            Conv2d(in_channels=1,out_channels=100,kernel_size=(5,self.word_vector_size),stride=1),
            Sigmoid(),
            MaxPool2d(kernel_size=(self.max_sentense_length - 4,1),stride=1)
        )])
        self.text_nn = Sequential(
            Linear(400,output_size),
            Sigmoid(),
        )
        if uniform == True:
            for i in range(4):
                init.uniform_(self.text_cnn[i][0].weight.data, 0, 0.001)
                init.uniform_(self.text_cnn[i][0].bias.data, 0, 0.001)
            init.uniform_(self.text_nn[0].weight.data, 0, 0.001)
            init.uniform_(self.text_nn[0].bias.data, 0, 0.001)
    def forward(self, input):
        return self.text_nn(
            cat([conv2d(input).squeeze_(-1).squeeze_(-1) for conv2d in self.text_cnn], 1)
        )

class GPABPR(Module):
    def __init__(self, user_set, item_set, embedding_weight ,metapath_feature, metapath_list_attributes,
        max_sentence = 83,  text_feature_dim=300, 
        visual_feature_dim = 2048, hidden_dim=512,
        uniform_value = 0.7):
        
        super(GPABPR, self) .__init__()
        self.epoch = 0
        self.uniform_value = uniform_value
        self.hidden_dim = hidden_dim
        # print(list(self.features.keys()))
        self.visual_nn = Sequential(
            Linear(visual_feature_dim, self.hidden_dim),
            Sigmoid(),
        )
        self.visual_nn[0].apply(lambda module: uniform_(module.weight.data,0,0.001))
        self.visual_nn[0].apply(lambda module: uniform_(module.bias.data,0,0.001))


        print('generating user & item Parmeters')
        
        # load text features
        self.max_sentense_length = max_sentence

        # text embedding layer
        self.text_embedding = Embedding.from_pretrained(embedding_weight, freeze=False)

        '''
            text features embedding layers
        '''
        self.vtbpr = VTBPR(user_set=user_set, item_set=item_set, metapath_feature=metapath_feature,metapath_list_attributes=metapath_list_attributes, hidden_dim=self.hidden_dim)
        self.textcnn = TextCNN(sentence_size=(max_sentence,text_feature_dim), output_size=hidden_dim)
        print('Module already prepared, {} users, {} items'.format(len(user_set), len(item_set)))



    def forward(self, batch, visual_features, text_features, can_s,**args):
        # pre deal 該batch 要處理的資料
        Us = [str(int(pair[0])) for pair in batch]  #user
        Is = [str(int(pair[1])) for pair in batch]  #item1
        Js = [str(int(pair[2])) for pair in batch]  #item2
        Ks = [str(int(pair[3])) for pair in batch]  #item unrelated

        Us = ['2362595']
        Is = ['8984476']
        Js = ['10441281']
        Ks = ['38812212']

        # part one General
        if not self.visual_nn[0].weight.data.is_cuda:
            #add dimension to the latent tensor
            #visual latent
            I_visual_latent = self.visual_nn(cat(
                [visual_features[I].unsqueeze(0) for I in Is], 0
            ))
            J_visual_latent = self.visual_nn(cat(
                [visual_features[J].unsqueeze(0) for J in Js], 0
            ))
            K_visual_latent = self.visual_nn(cat(
                [visual_features[K].unsqueeze(0) for K in Ks], 0
            ))
            #contextual latent
            I_text_latent = self.textcnn( 
                self.text_embedding( 
                    cat(
                        [text_features[I].unsqueeze(0) for I in Is], 0
                    )
                ) .unsqueeze_(1)
            )
            J_text_latent = self.textcnn( 
                self.text_embedding( 
                    cat(
                        [text_features[J].unsqueeze(0) for J in Js], 0
                    )
                ).unsqueeze_(1)
            )
            K_text_latent = self.textcnn( 
                self.text_embedding( 
                    cat(
                        [text_features[K].unsqueeze(0) for K in Ks], 0
                    )
                ) .unsqueeze_(1)
            )

        else : #cuda implementation
            with torch.cuda.device(self.visual_nn[0].weight.data.get_device()):
                stream1 = torch.cuda.Stream()
                stream2 = torch.cuda.Stream()
                I_visual_latent = self.visual_nn(cat(
                    [visual_features[I].unsqueeze(0) for I in Is], 0
                ).cuda())
                with torch.cuda.stream(stream1):
                    J_visual_latent = self.visual_nn(cat(
                        [visual_features[J].unsqueeze(0) for J in Js], 0
                    ).cuda())
                with torch.cuda.stream(stream2):
                    K_visual_latent = self.visual_nn(cat(
                        [visual_features[K].unsqueeze(0) for K in Ks], 0
                    ).cuda())
                I_text_latent = self.textcnn( 
                    self.text_embedding( 
                        cat(
                            [text_features[I].unsqueeze(0) for I in Is], 0
                        ).cuda() 
                    ) .unsqueeze_(1)
                )
                with torch.cuda.stream(stream1):
                    J_text_latent = self.textcnn( 
                        self.text_embedding( 
                            cat(
                                [text_features[J].unsqueeze(0) for J in Js], 0
                            ) .cuda()
                        ).unsqueeze_(1)
                    )
                with torch.cuda.stream(stream2):
                    K_text_latent = self.textcnn( 
                        self.text_embedding( 
                            cat(
                                [text_features[K].unsqueeze(0) for K in Ks], 0
                            ) .cuda()
                        ) .unsqueeze_(1)
                    )
        # part 2 cuj
        torch.cuda.synchronize()
        stream1 = torch.cuda.Stream()
        stream2 = torch.cuda.Stream()
        visual_ij = bmm( I_visual_latent.unsqueeze(1), J_visual_latent .unsqueeze(-1)).squeeze_(-1).squeeze_(-1)
        with torch.cuda.stream(stream1):
            text_ij = bmm( I_text_latent.unsqueeze(1), J_text_latent .unsqueeze(-1)).squeeze_(-1).squeeze_(-1)
            cuj = self.vtbpr(Us, Js, J_visual_latent, J_text_latent)
        visual_ik = bmm( I_visual_latent.unsqueeze(1), K_visual_latent .unsqueeze(-1)).squeeze_(-1).squeeze_(-1)
        with torch.cuda.stream(stream2):
            text_ik = bmm( I_text_latent .unsqueeze(1), K_text_latent .unsqueeze(-1)).squeeze_(-1).squeeze_(-1)
            cuk = self.vtbpr(Us, Ks, K_visual_latent, K_text_latent)
        
        torch.cuda.synchronize()
        p_ij = 0.5 * visual_ij + 0.5 * text_ij
        p_ik = 0.5 * visual_ik + 0.5 * text_ik
        f_ij = self.uniform_value * p_ij + (1 - self.uniform_value) * cuj
        #f_ik = self.uniform_value * p_ik + (1 - self.uniform_value) * cuk

        # add candidates to calculate the mrr, bmm需要再算9組p_ik
        #candidates = torch.empty(1,can_s).cuda()
        candidates = []
        #candidates_idx = []
        #print(f_ij.cpu().detach().numpy().tolist()[0])
        #print(cuk.cpu().detach().numpy().tolist()[0])
        i = 0

        # Is = ['11484712']
        # Js = ['10995355']
        # Ks = ['9134104', '20448634', '21748407', '9808091', '14866360', '38450807', '19131143', '8752259', '9431371']
        Ks = ['38812212','11863252','3686052','38452601','37693348','46750380','29412036','38459611','12227345','5737629','47109305','11751237','7341332','32389244','7683245','38358765','9295192','11792072','15957183']

        for I in Is :
            with torch.cuda.device(self.visual_nn[0].weight.data.get_device()):
                I_visual_latent_tmp = self.visual_nn(visual_features[I].unsqueeze(0).cuda())
                I_text_latent_tmp = self.textcnn( self.text_embedding(text_features[I].unsqueeze(0).cuda()) .unsqueeze_(1))
                # visual_ij = bmm( I_visual_latent.unsqueeze(1), J_visual_latent .unsqueeze(-1)).squeeze_(-1).squeeze_(-1)
                # text_ij = bmm( I_text_latent.unsqueeze(1), J_text_latent .unsqueeze(-1)).squeeze_(-1).squeeze_(-1)
                # p_ij2 = 0.5 * visual_ij + 0.5 * text_ij
                # f_ij2 = self.uniform_value * p_ij + (1 - self.uniform_value) * cuj
                
                bucket = []
                bucket_idx = []

                # if can_s == len(batch):
                #     Ks = Ks
                # else:
                #     Ks = random.sample(Ks, can_s-1)
                for K in Ks:
                    with torch.cuda.stream(stream2):
                        K_visual_latent_tmp = self.visual_nn(visual_features[K].unsqueeze(0).cuda())
                        visual_ik_tmp = bmm(I_visual_latent_tmp.unsqueeze(1), K_visual_latent_tmp.unsqueeze(-1)).squeeze_(-1).squeeze_(-1)
                        K_text_latent_tmp = self.textcnn(self.text_embedding(text_features[K].unsqueeze(0).cuda()).unsqueeze_(1))
                        text_ik_tmp = bmm( I_text_latent_tmp .unsqueeze(1), K_text_latent_tmp .unsqueeze(-1)).squeeze_(-1).squeeze_(-1)
                        p_ik_tmp = 0.5 * visual_ik_tmp + 0.5 * text_ik_tmp
                        
                        K_visual_latent = self.visual_nn(cat([visual_features[K].unsqueeze(0)], 0).cuda())
                        K_text_latent = self.textcnn(self.text_embedding(cat([text_features[K].unsqueeze(0)], 0) .cuda()) .unsqueeze_(1))
                        cuk = self.vtbpr(Us, [K], K_visual_latent, K_text_latent)
                       
                        # cuk = self.vtbpr(Us, Ks, K_visual_latent_tmp, K_text_latent_tmp)
                        cuk_tmp = torch.tensor(cuk.cpu().detach().numpy()).cuda()
                        # print(cuk_tmp)
                        # print('p_ik_tmp:', p_ik_tmp.size())
                        # print('cuk:', cuk.size())
                        # print('cuk_tmp:', cuk_tmp.size())
                        f_ik = self.uniform_value * p_ik_tmp + (1 - self.uniform_value) * cuk_tmp
                        # print('f_ik size:',f_ik.size())
                        bucket.append(f_ik.item())
                        bucket_idx.append(K)
                #bucket.insert(0, torch.tensor(f_ij.cpu().detach().numpy()[i]))
                bucket.insert(0, f_ij.cpu().detach().numpy()[i])
                bucket_idx.insert(0, Js[i])
                #get examples for ranking list
                print("Query Item:",I)
                print("Index List:",Js[i])
                print("Ranking Results:",dict(sorted(dict(zip(bucket_idx, bucket)).items(), key=lambda x: x[1], reverse=True)).keys())
                i += 1
                #bucket = torch.tensor(bucket).cuda()
                candidates.append(bucket)
                #candidates = stack((candidates, bucket.unsqueeze(0)), 0)



        # union
        return self.uniform_value * p_ij + (1 - self.uniform_value) * cuj \
            - ( self.uniform_value * p_ik + (1 - self.uniform_value) * cuk ), candidates
    def fit(self, batch, visual_features, text_features, **args):
        """
            with the same input as forward and return a loss with weight regularaition
        """

        Us = [str(int(pair[0])) for pair in batch]
        Is = [str(int(pair[1])) for pair in batch]
        Js = [str(int(pair[2])) for pair in batch]
        Ks = [str(int(pair[3])) for pair in batch]
        if not self.visual_nn[0].weight.data.is_cuda:
            I_visual_latent = self.visual_nn(cat(
                [visual_features[I].unsqueeze(0) for I in Is], 0
            ))
            J_visual_latent = self.visual_nn(cat(
                [visual_features[J].unsqueeze(0) for J in Js], 0
            ))
            K_visual_latent = self.visual_nn(cat(
                [visual_features[K].unsqueeze(0) for K in Ks], 0
            ))
            I_text_latent = self.textcnn( 
                self.text_embedding( 
                    cat(
                        [text_features[I].unsqueeze(0) for I in Is], 0
                    )
                ) .unsqueeze_(1)
            )
            J_text_latent = self.textcnn( 
                self.text_embedding( 
                    cat(
                        [text_features[J].unsqueeze(0) for J in Js], 0
                    )
                ).unsqueeze_(1)
            )
            K_text_latent = self.textcnn( 
                self.text_embedding( 
                    cat(
                        [text_features[K].unsqueeze(0) for K in Ks], 0
                    )
                ) .unsqueeze_(1)
            )

        else :
            with torch.cuda.device(self.visual_nn[0].weight.data.get_device()):
                stream1 = torch.cuda.Stream()
                stream2 = torch.cuda.Stream()
                I_visual_latent = self.visual_nn(cat(
                    [visual_features[I].unsqueeze(0) for I in Is], 0
                ).cuda())
                with torch.cuda.stream(stream1):
                    J_visual_latent = self.visual_nn(cat(
                        [visual_features[J].unsqueeze(0) for J in Js], 0
                    ).cuda())
                with torch.cuda.stream(stream2):
                    K_visual_latent = self.visual_nn(cat(
                        [visual_features[K].unsqueeze(0) for K in Ks], 0
                    ).cuda())
                I_text_latent = self.textcnn( 
                    self.text_embedding( 
                        cat(
                            [text_features[I].unsqueeze(0) for I in Is], 0
                        ).cuda() 
                    ) .unsqueeze_(1)
                )
                with torch.cuda.stream(stream1):
                    J_text_latent = self.textcnn( 
                        self.text_embedding( 
                            cat(
                                [text_features[J].unsqueeze(0) for J in Js], 0
                            ) .cuda()
                        ).unsqueeze_(1)
                    )
                with torch.cuda.stream(stream2):
                    K_text_latent = self.textcnn( 
                        self.text_embedding( 
                            cat(
                                [text_features[K].unsqueeze(0) for K in Ks], 0
                            ) .cuda()
                        ) .unsqueeze_(1)
                    )
        # part 2 cuj
        torch.cuda.synchronize()
        stream1 = torch.cuda.Stream()
        stream2 = torch.cuda.Stream()
        visual_ij = bmm( I_visual_latent.unsqueeze(1), J_visual_latent .unsqueeze(-1)).squeeze_(-1).squeeze_(-1)
        with torch.cuda.stream(stream1):
            text_ij = bmm( I_text_latent.unsqueeze(1), J_text_latent .unsqueeze(-1)).squeeze_(-1).squeeze_(-1)
            cuj, cujweight = self.vtbpr.fit(Us, Js, J_visual_latent, J_text_latent)
        visual_ik = bmm( I_visual_latent.unsqueeze(1), K_visual_latent .unsqueeze(-1)).squeeze_(-1).squeeze_(-1)
        with torch.cuda.stream(stream2):
            text_ik = bmm( I_text_latent .unsqueeze(1), K_text_latent .unsqueeze(-1)).squeeze_(-1).squeeze_(-1)
            cuk, cukweight = self.vtbpr.fit(Us, Ks, K_visual_latent, K_text_latent)
        
        torch.cuda.synchronize()
        
        p_ij = 0.5 * visual_ij + 0.5 * text_ij
        p_ik = 0.5 * visual_ik + 0.5 * text_ik
        
        cujkweight = self.vtbpr.get_user_gama(set(Us)).norm(p=2) \
            + self.vtbpr.get_theta_user_visual(set(Us)).norm(p=2) + self.vtbpr.get_theta_user_text(set(Us)).norm(p=2) \
            + self.vtbpr.get_item_gama(set(Js+Ks)).norm(p=2)
        
        
        # union
        return self.uniform_value * p_ij + (1 - self.uniform_value) * cuj \
            - ( self.uniform_value * p_ik + (1 - self.uniform_value) * cuk ) ,\
                cujkweight + self.text_embedding( 
                            cat(
                                [text_features[J].unsqueeze(0) for J in set(Is+Js+Ks)], 0
                            ).cuda()
                        ).norm(p=2)
      