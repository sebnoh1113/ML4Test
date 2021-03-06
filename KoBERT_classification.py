import pickle
import pandas as pd
import numpy as np
from datetime import datetime
from tqdm import tqdm

from sklearn.model_selection import train_test_split
# from keras.preprocessing.sequence import pad_sequence

import torch
import torch.nn as nn
# import torch.nn.functional as F
# import torch.optim as optim
from torch.utils.data import Dataset, DataLoader

from transformers import BertForSequenceClassification
from transformers import AdamW
from transformers.optimization import get_cosine_schedule_with_warmup

from typing import Any, Dict, List, Optional
from transformers.tokenization_utils import AddedToken
from transformers import XLNetTokenizer
from transformers import SPIECE_UNDERLINE

# from transformers import AutoTokenizer, AutoModel
# tokenizer = AutoTokenizer.from_pretrained("skt/kobert-base-v1")
# model = AutoModel.from_pretrained("skt/kobert-base-v1")
# result = kobert_tokenizer.tokenize("너는 내년 대선 때 투표할 수 있어?")
# print(result)
# kobert_vocab = kobert_tokenizer.get_vocab()
# print(kobert_vocab.get('▁대선'))
# print([kobert_tokenizer.encode(token) for token in result])

# from transformers import AutoTokenizer, AutoModelForMaskedLM
# kcbert의 tokenizer와 모델을 불러옴.
# kcbert_tokenizer = AutoTokenizer.from_pretrained("beomi/kcbert-base")
# kcbert = AutoModelForMaskedLM.from_pretrained("beomi/kcbert-base")
# result = kcbert_tokenizer.tokenize("너는 내년 대선 때 투표할 수 있어?")
# print(result)
# print(kcbert_tokenizer.vocab['대선'])
# print([kcbert_tokenizer.encode(token) for token in result])

dataFileName = './dfFinal.csv'
x_dataFieldName = 'precSentences'
y_dataFieldName = 'case_sort'

sampleRatio = 1 # 실전의 경우 1
targetDimension = 512 # pretrained model에 따라 조정
num_labels = 7 # transfer learing 데이터에 따라 조정
dr_rate = 0.4
    
batch_size = 2
epochs = 100 

# AdamW 사용시 필요
warmup_steps = None
warmup_ratio = 0.1
weight_decay = 0.01

max_grad_norm = 1
log_interval = 100
learning_rate = 5e-5
early_stopping_criteria=5


class KoBERTTokenizer(XLNetTokenizer):
    padding_side = "right"

    def __init__(
        self,
        vocab_file,
        do_lower_case=False,
        remove_space=True,
        keep_accents=False,
        bos_token="[CLS]",
        eos_token="[SEP]",
        unk_token="[UNK]",
        sep_token="[SEP]",
        pad_token="[PAD]",
        cls_token="[CLS]",
        mask_token="[MASK]",
        additional_special_tokens=None,
        sp_model_kwargs: Optional[Dict[str, Any]] = None,
        **kwargs
    ) -> None:
        # Mask token behave like a normal word, i.e. include the space before it
        mask_token = (
            AddedToken(mask_token, lstrip=True, rstrip=False)
            if isinstance(mask_token, str)
            else mask_token
        )

        self.sp_model_kwargs = {} if sp_model_kwargs is None else sp_model_kwargs

        super().__init__(
            vocab_file,
            do_lower_case=do_lower_case,
            remove_space=remove_space,
            keep_accents=keep_accents,
            bos_token=bos_token,
            eos_token=eos_token,
            unk_token=unk_token,
            sep_token=sep_token,
            pad_token=pad_token,
            cls_token=cls_token,
            mask_token=mask_token,
            additional_special_tokens=additional_special_tokens,
            sp_model_kwargs=self.sp_model_kwargs,
            **kwargs,
        )
        self._pad_token_type_id = 0

    def build_inputs_with_special_tokens(
        self, token_ids_0: List[int], token_ids_1: Optional[List[int]] = None
    ) -> List[int]:
        """
        Build model inputs from a sequence or a pair of sequence for sequence classification tasks by concatenating and
        adding special tokens. An XLNet sequence has the following format:
        - single sequence: ``<cls> X <sep>``
        - pair of sequences: ``<cls> A <sep> B <sep>``
        Args:
            token_ids_0 (:obj:`List[int]`):
                List of IDs to which the special tokens will be added.
            token_ids_1 (:obj:`List[int]`, `optional`):
                Optional second list of IDs for sequence pairs.
        Returns:
            :obj:`List[int]`: List of `input IDs <../glossary.html#input-ids>`__ with the appropriate special tokens.
        """
        sep = [self.sep_token_id]
        cls = [self.cls_token_id]
        if token_ids_1 is None:
            return cls + token_ids_0 + sep
        return cls + token_ids_0 + sep + token_ids_1 + sep

    def _tokenize(self, text: str) -> List[str]:
        """Tokenize a string."""
        text = self.preprocess_text(text)
        pieces = self.sp_model.encode(text, out_type=str, **self.sp_model_kwargs)
        new_pieces = []
        for piece in pieces:
            if len(piece) > 1 and piece[-1] == str(",") and piece[-2].isdigit():
                cur_pieces = self.sp_model.EncodeAsPieces(
                    piece[:-1].replace(SPIECE_UNDERLINE, "")
                )
                if (
                    piece[0] != SPIECE_UNDERLINE
                    and cur_pieces[0][0] == SPIECE_UNDERLINE
                ):
                    if len(cur_pieces[0]) == 1:
                        cur_pieces = cur_pieces[1:]
                    else:
                        cur_pieces[0] = cur_pieces[0][1:]
                cur_pieces.append(piece[-1])
                new_pieces.extend(cur_pieces)
            else:
                new_pieces.append(piece)

        return new_pieces

    def build_inputs_with_special_tokens(
        self, token_ids_0: List[int], token_ids_1: Optional[List[int]] = None
    ) -> List[int]:
        """
        Build model inputs from a sequence or a pair of sequence for sequence classification tasks by concatenating and
        adding special tokens. An XLNet sequence has the following format:
        - single sequence: ``<cls> X <sep> ``
        - pair of sequences: ``<cls> A <sep> B <sep>``
        Args:
            token_ids_0 (:obj:`List[int]`):
                List of IDs to which the special tokens will be added.
            token_ids_1 (:obj:`List[int]`, `optional`):
                Optional second list of IDs for sequence pairs.
        Returns:
            :obj:`List[int]`: List of `input IDs <../glossary.html#input-ids>`__ with the appropriate special tokens.
        """
        sep = [self.sep_token_id]
        cls = [self.cls_token_id]
        if token_ids_1 is None:
            return cls + token_ids_0 + sep
        return cls + token_ids_0 + sep + token_ids_1 + sep

    def create_token_type_ids_from_sequences(
        self, token_ids_0: List[int], token_ids_1: Optional[List[int]] = None
    ) -> List[int]:
        """
        Create a mask from the two sequences passed to be used in a sequence-pair classification task. An XLNet
        sequence pair mask has the following format:
        ::
            0 0 0 0 0 0 0 0 0 0 0 1 1 1 1 1 1 1 1 1
            | first sequence    | second sequence |
        If :obj:`token_ids_1` is :obj:`None`, this method only returns the first portion of the mask (0s).
        Args:
            token_ids_0 (:obj:`List[int]`):
                List of IDs.
            token_ids_1 (:obj:`List[int]`, `optional`):
                Optional second list of IDs for sequence pairs.
        Returns:
            :obj:`List[int]`: List of `token type IDs <../glossary.html#token-type-ids>`_ according to the given
            sequence(s).
        """
        sep = [self.sep_token_id]
        cls = [self.cls_token_id]
        if token_ids_1 is None:
            return len(cls + token_ids_0 + sep) * [0]
        return len(cls + token_ids_0 + sep) * [0] + len(token_ids_1 + sep) * [1]


class Vocabulary(object):
    
    """매핑을 위해 텍스트를 처리하고 어휘 사전을 만드는 클래스 """

    def __init__(self, token_to_idx=None):
        """
        매개변수:
            token_to_idx (dict): 기존 토큰-인덱스 매핑 딕셔너리
        """

        if token_to_idx is None:
            token_to_idx = {}
        self._token_to_idx = token_to_idx

        self._idx_to_token = {idx: token 
                              for token, idx in self._token_to_idx.items()}
        
    # def to_serializable(self):
        # """ 직렬화할 수 있는 딕셔너리를 반환합니다 """
        # return {'token_to_idx': self._token_to_idx}

    # @classmethod
    # def from_serializable(cls, contents):
        # """ 직렬화된 딕셔너리에서 Vocabulary 객체를 만듭니다 """
        # return cls(**contents)

    def add_token(self, token):
        """ 토큰을 기반으로 매핑 딕셔너리를 업데이트합니다

        매개변수:
            token (str): Vocabulary에 추가할 토큰
        반환값:
            index (int): 토큰에 상응하는 정수
        """
        if token in self._token_to_idx:
            index = self._token_to_idx[token]
        else:
            index = len(self._token_to_idx)
            self._token_to_idx[token] = index
            self._idx_to_token[index] = token
        return index
            
    def add_many(self, tokens):
        """토큰 리스트를 Vocabulary에 추가합니다.
        
        매개변수:
            tokens (list): 문자열 토큰 리스트
        반환값:
            indices (list): 토큰 리스트에 상응되는 인덱스 리스트
        """
        return [self.add_token(token) for token in tokens]

    def lookup_token(self, token):
        """토큰에 대응하는 인덱스를 추출합니다.
        
        매개변수:
            token (str): 찾을 토큰 
        반환값:
            index (int): 토큰에 해당하는 인덱스
        """
        return self._token_to_idx[token]

    def lookup_index(self, index):
        """ 인덱스에 해당하는 토큰을 반환합니다.
        
        매개변수: 
            index (int): 찾을 인덱스
        반환값:
            token (str): 인텍스에 해당하는 토큰
        에러:
            KeyError: 인덱스가 Vocabulary에 없을 때 발생합니다.
        """
        if index not in self._idx_to_token:
            raise KeyError("the index (%d) is not in the Vocabulary" % index)
        return self._idx_to_token[index]

    def __str__(self):
        return "<Vocabulary(size=%d)>" % len(self)

    def __len__(self):
        return len(self._token_to_idx)

def vectorize(vectorizer, data, field, length):
    
    vectorized = vectorizer(data[field])
        
    if len(vectorized['input_ids']) >= length:
        inputIds = vectorized['input_ids'][:length-1]
        inputIds.append(3)
    else:
        inputIds = [ 0 for x in range(length)]
        inputIds[: len(vectorized['input_ids'])] = vectorized['input_ids']
        
    if len(vectorized['attention_mask']) >= length:
        attentionMask = vectorized['attention_mask'][:length]
    else:
        attentionMask = [ 0 for x in range(length)]
        attentionMask[: len(vectorized['attention_mask'])] = vectorized['attention_mask']
                
    if len(vectorized['token_type_ids']) >= length:
        tokenTypeIds = vectorized['token_type_ids'][:length]
    else:
        tokenTypeIds = [ 0 for x in range(length)]
        tokenTypeIds[: len(vectorized['token_type_ids'])] = vectorized['token_type_ids']

    # print('\n', len(inputIds), len(attentionMask), len(tokenTypeIds))
    return (inputIds, attentionMask, tokenTypeIds)

def dataloader_factory(device, df, x_dataFieldName, targetDimension, batch_size):       
    # vectorizing
    print("vectorizing...")
    data = {'input_ids':[], 'attention_mask': [], 'token_type_ids': [], 'label': []}
    
    for i in tqdm(range(len(df))):
        tuple = vectorize(tokenizer, df.iloc[i], x_dataFieldName, targetDimension)
        data['input_ids'].append(tuple[0])
        data['attention_mask'].append(tuple[1])
        data['token_type_ids'].append(tuple[2])
        data['label'].append(df.iloc[i]['label'])
        
    datadf = pd.DataFrame(data)
    print(datadf.info())
    print(datadf.head())
    print()
    
    # dataloader setting
    print("Torch Dataset / Torch DataLoader instantiating...")
    dataset = BERTDataset(data, device)

    dataLoader = DataLoader(dataset, 
                            batch_size=batch_size, 
                            shuffle = True, 
                            # collate_fn=lambda x:x # 배치 리스트 요소를 데이터 개별 인스턴스로 세팅
                            )
    print("done!")
    print()
    return dataLoader, dataset

class BERTDataset(Dataset):
    
    def __init__(self, dataset, device):

        self.dataset = dataset # python dictionary type dataset
        
    def __getitem__(self, index):
        """파이토치 데이터셋의 주요 진입 메서드
        
        매개변수:
            index (int): 데이터 포인트의 인덱스
        반환값:
            데이터 포인트의 특성(x_data)과 레이블(y_target) 등으로 이루어진 딕셔너리
        """
        
        input_ids = \
            torch.LongTensor(np.array(self.dataset['input_ids'][index])).to(device)
        attention_mask = \
            torch.LongTensor(np.array(self.dataset['attention_mask'][index])).to(device)
        
        token_type_ids = \
            torch.LongTensor(np.array(self.dataset['token_type_ids'][index])).to(device)
        
        label = \
            torch.LongTensor(np.array([self.dataset['label'][index]])).to(device)
        # print()
        # print("index and label: ")
        # print(index)       
        # print(label)
        # print()
        
        return [input_ids, attention_mask, token_type_ids, label]

    def __len__(self):
        return (len(self.dataset['label']))

'''      
class BERTClassifier(nn.Module):
    def __init__(self,
                 bert,
                 hidden_size = targetDimension,
                 num_classes=num_labels,
                 dr_rate=dr_rate,
                 ):
        super(BERTClassifier, self).__init__()
        self.bert = bert
        # self.dr_rate = dr_rate
                 
        # self.classifier = nn.Linear(hidden_size , num_classes)
        # if dr_rate:
        #     self.dropout = nn.Dropout(p=dr_rate)
    
    def forward(self, input_ids, attention_mask, token_type_ids): 
        # overriding __call__() function
        
        pooler = self.bert(input_ids=input_ids, 
                           token_type_ids = token_type_ids, 
                           attention_mask = attention_mask)
        
        # print(pooler)
        # input()
        
        # if self.dr_rate:
        #     out = self.dropout(pooler)
        # else:
        #     out = pooler
            
        # return self.classifier(out)
        
        return pooler
'''

#정확도 측정을 위한 함수 정의
def calc_accuracy(logitsTensorList,labelList):
    max_vals, max_indices = torch.max(logitsTensorList, 1) #
    train_acc = (max_indices == labelList).sum().data.cpu().numpy()/max_indices.size()[0] ###################################################################################################
    # 두 리스트의 같은 위치의 요소를 비교해서 조건식을 충족하는 경우에는 그 충족 횟수의 합계를 내고
    # 그 합계를 리스트의 요소 갯수로 나누어 점수를 구함
    return train_acc
    
def predict(predict_sentence):
        
    data = {'precSentences': predict_sentence, 'label': 0}
    dataloader= dataloader_factory(device, pd.DataFrame(data), x_dataFieldName, targetDimension, 1)[0]
    
    bertmodel.eval()

    for batch_id, item in enumerate(dataloader):
        
        input_ids, attention_mask, token_type_ids = item
        
        out = bertmodel(input_ids, attention_mask, token_type_ids)

        test_eval=[]
        for i in out.logits:
            logits=i
            logits = logits.detach().cpu().numpy()     #####################################################################################################################################################

            if np.argmax(logits) == 0:
                test_eval.append("민사")
            elif np.argmax(logits) == 1:
                test_eval.append("행정")
            elif np.argmax(logits) == 2:
                test_eval.append("형사")
            elif np.argmax(logits) == 3:
                test_eval.append("특허")
            elif np.argmax(logits) == 4:
                test_eval.append("가정")
            elif np.argmax(logits) == 5:
                test_eval.append("신청")
            elif np.argmax(logits) == 6:
                test_eval.append("특별")

        print(">> 입력하신 내용은 " + test_eval[0] + " 사건에 해당합니다.")



#################################### 최상 모델 저장을 위해 ############################################################################
def make_train_state():
    return {'stop_early': False,
            'early_stopping_step': 0,
            'early_stopping_best_val': 1e8,
            'learning_rate': learning_rate,
            'epoch_index': 0,
            'train_loss': [],
            'train_acc': [],
            'loss': [],
            'acc': [],
            'test_loss': -1,
            'test_acc': -1,
            'model_filename': 'best_model'}


def update_train_state(model, train_state):
    """ 훈련 상태를 업데이트합니다.

    Components:
        - 조기 종료: 과대 적합 방지
        - 모델 체크포인트: 더 나은 모델을 저장합니다

    :param args: 메인 매개변수
    :param model: 훈련할 모델
    :param train_state: 훈련 상태를 담은 딕셔너리
    :returns:
        새로운 훈련 상태
    """

    # 적어도 한 번 모델을 저장합니다
    if train_state['epoch_index'] == 0:
        torch.save(model.state_dict(), train_state['model_filename'])
        train_state['stop_early'] = False

    # 성능이 향상되면 모델을 저장합니다
    elif train_state['epoch_index'] >= 1:
        loss_tm1, loss_t = train_state['loss'][-2:]

        # 손실이 나빠지면
        if loss_t >= train_state['early_stopping_best_val']:
            # 조기 종료 단계 업데이트
            train_state['early_stopping_step'] += 1
        # 손실이 감소하면
        else:
            # 최상의 모델 저장
            if loss_t < train_state['early_stopping_best_val']:
                torch.save(model.state_dict(), train_state['model_filename'])
                with open(f"bert{e}model{batch_id}.model", 'wb') as f:
                    pickle.dump(bertmodel, f)

            # 조기 종료 단계 재설정
            train_state['early_stopping_step'] = 0

        # 조기 종료 여부 확인
        train_state['stop_early'] = \
            train_state['early_stopping_step'] >= early_stopping_criteria

    return train_state

if __name__ == '__main__' :
    
    # CUDA 체크
    cuda=True
    if not torch.cuda.is_available():
        cuda = False        
    device = torch.device("cuda" if cuda else "cpu")
    print("CUDA 사용여부: {}".format(cuda))

    # model loading
    print("model loading...")
    model = \
        BertForSequenceClassification.from_pretrained('skt/kobert-base-v1', num_labels=num_labels)
    with open('kobertbasev1model.pickle', 'wb') as f:
        pickle.dump(model, f, pickle.HIGHEST_PROTOCOL)
    with open('kobertbasev1model.pickle', 'rb') as f:
        model = pickle.load(f)
    print()
         
    # toke0nizer loading
    print("tokenizer loading...")
    tokenizer = KoBERTTokenizer.from_pretrained('skt/kobert-base-v1')
    with open('kobertbasev1tokenizer.pickle', 'wb') as f:
        pickle.dump(tokenizer, f, pickle.HIGHEST_PROTOCOL)
    with open('kobertbasev1tokenizer.pickle', 'rb') as f:
        tokenizer = pickle.load(f)
    print()
 
    # dataset loading (DataFrame)
    print("dataset loading....")
    dfFinal = pd.read_csv(dataFileName)
    dfFinal['label']=None
    print()
    
    # labeling
    print("labeling...")
    vocabLabel = Vocabulary()
    vocabLabel.add_many(dfFinal[y_dataFieldName].tolist())
    print('num of case sorts: ')
    print(len(vocabLabel))
    print()
    for i in range(len(vocabLabel)):
        print("Category Number: ")
        print(i)
        print("Case Sort Code: ")
        print(vocabLabel.lookup_index(i))
        print()
    for i in range(len(dfFinal)):
        temp = vocabLabel.lookup_token(dfFinal.iloc[i][y_dataFieldName]) # dataframe.iloc[i] -> Series
        dfFinal.loc[i, 'label'] = temp # dataframe.iloc[i] -> Series with NO WARNING
    print(dfFinal.info())
    with open('labeleddf.pickle', 'wb') as f:
        pickle.dump(dfFinal, f, pickle.HIGHEST_PROTOCOL)
    with open('labeleddf.pickle', 'rb') as f:
        df = pickle.load(f)
    print(df['label'].value_counts())
    print()
    print("label truncating...")
    df = df.drop(df[df['label'] == 2].index)
    df = df.drop(df[df['label'] == 1].index)
    df = df.drop(df[df['label'] == 5].index)
    df = df.drop(df[df['label'] == 9].index)
    df = df.drop(df[df['label'] == 3].index)
    df = df.drop(df[df['label'] == 6].index)
    print(df['label'].value_counts())
    print()
    print("label to index...")
    df.loc[df['label']==4,  'label']= 'civil'
    df.loc[df['label']==11, 'label']= 'admin'
    df.loc[df['label']==12, 'label']= 'crimi'
    df.loc[df['label']==10, 'label']= 'paten'
    df.loc[df['label']==0,  'label']= 'famil'
    df.loc[df['label']==8,  'label']= 'apply'
    df.loc[df['label']==7,  'label']= 'speci'
    print(df['label'].value_counts())
    print()
    df.loc[df['label']=='civil', 'label']= 0
    df.loc[df['label']=='admin', 'label']= 1
    df.loc[df['label']=='crimi', 'label']= 2
    df.loc[df['label']=='paten', 'label']= 3
    df.loc[df['label']=='famil', 'label']= 4
    df.loc[df['label']=='apply', 'label']= 5
    df.loc[df['label']=='speci', 'label']= 6
    print(df['label'].value_counts())
    print()
    
    # dataset splitting 
    print("train / test datasets splitting...")
    xTrain, xTest, yTrain, yTest = \
        train_test_split(df['precSentences'], df['label'], \
        test_size=0.2, random_state= 42, shuffle=True, stratify=df['label'])
    dfTrain = pd.concat((xTrain, yTrain), axis = 1)
    dfTest = pd.concat((xTest, yTest), axis = 1)
    print(dfTrain.info())
    print(dfTrain.head())
    print()
    print(dfTest.info())
    print(dfTest.tail())
    print()
    
    # dataset sampling
    print("train / test dataset sampling...")
    dfTrainSample = dfTrain.sample(frac=sampleRatio, random_state=999)
    dfTestSample = dfTest.sample(frac=sampleRatio, random_state=999)
    print()
    
    print("DATA VECTORIZING AND LOADING ON DATALOADER OBJECT...")
    print()
    ###########################################
    print("train dataset...")
    print(dfTrainSample.info())
    print()
    train_loader, dataset = dataloader_factory(device, dfTrainSample, 
                                      x_dataFieldName, 
                                      targetDimension,
                                      batch_size=batch_size,
                                    
                                      )
    ###########################################
    print("test dataset...")
    print(dfTestSample.info())
    print()
    test_loader = dataloader_factory(device,dfTestSample, 
                                     x_dataFieldName, 
                                     targetDimension,
                                     batch_size=batch_size,
                                     
                                     )[0] 
    ###########################################
    



    # TRAINING
    print("Press Enter Key for training your model...")
    # input()
    
    # model object setting
    bertmodel = model
    bertmodel.to(device)######################################################################################################
    
    # optimizer와 scheduler 설정
    t_total = len(train_loader) * epochs
    warmup_steps = int(t_total * warmup_ratio)
    no_decay = ['bias', 'LayerNorm.weight']
    optimizer_grouped_parameters = [
        {'params': [p for n, p in bertmodel.named_parameters() if not any(nd in n for nd in no_decay)], 'weight_decay': 0.01},
        {'params': [p for n, p in bertmodel.named_parameters() if any(nd in n for nd in no_decay)], 'weight_decay': 0.0}
    ]
    
    optimizer = AdamW(optimizer_grouped_parameters, lr=learning_rate)
    scheduler = \
        get_cosine_schedule_with_warmup(
            optimizer, 
            num_warmup_steps=warmup_steps, 
            num_training_steps=t_total)

    # loss function setting
    
    # dataset.class_weights = dataset.class_weights.to(device)     ## BERTDataset object has no attribute 'class_weights' 
        
    loss_fn = nn.CrossEntropyLoss()   ## BERTDataset object has no attribute 'class_weights' 
    # loss_fn = nn.CrossEntropyLoss()
   
    train_state = make_train_state()


    # GO! 
    train_history=[]
    test_history=[]
    loss_history=[]
    
    for e in range(epochs):
        train_state['epoch_index'] = e
        
        train_acc = 0.0
        test_acc = 0.0
        
        #TRAINING
        bertmodel.train()
        for batch_id, batch in enumerate(tqdm(train_loader)):
            if batch_id % log_interval == 0 : 
                print(f"Epoch : {e+1} in {epochs} / Minibatch Step : {batch_id}")

            # print(type(item))
            # print(item)
            # print(item.__dir__)
         
            input_ids, attention_mask, token_type_ids, label = batch

            # input_ids.to(device) ################################################################################
            # attention_mask.to(device) ############################################################################
            # token_type_ids.to(device) ########################################################
            label = label.squeeze(1)
            # label.to(device) ######################################
            
            # print(input_ids)
            # print(attention_mask)
            # print(token_type_ids)
            # print(label)
            
            # input()
            
            #1 gradient를 0으로 초기화
            optimizer.zero_grad()
            
            #2 출력 계산
            out = bertmodel(input_ids, 
                            attention_mask = attention_mask, 
                            token_type_ids = token_type_ids, 
                            # labels=label
                            ) 
            # print()
            # print("out:")
            # print(out)
            # print(type(out))
            # print("label:")
            # print(label)
            # print(type(label))
                        
            #3 손실 계산
            loss = loss_fn(out.logits, label)
            # loss = out.loss
            # print(loss)
            # input()
            
            #4 손실로 gradient 계산
            loss.backward() 
            torch.nn.utils.clip_grad_norm_(bertmodel.parameters(), max_grad_norm)
            
            #5 계산된 gradient로 가중치를 갱신
            optimizer.step()
            
            #6 Update learning rate schedule
            scheduler.step()  
            
            #7 정확도 계산
            train_acc += calc_accuracy(out.logits, label)
            # train_acc += loss.item()
                     
            if batch_id % log_interval == 0:
                print("epoch {} batch id {} loss {} train acc {}".format(e+1, batch_id+1, loss.data.cpu().numpy(), train_acc / (batch_id+1)))
            #     train_history.append(train_acc / (batch_id+1))
            #     loss_history.append(loss.data.cpu().numpy())
            #     # with open(f"bert{e}model{batch_id}.model", 'wb') as f:
            #     #     pickle.dump(bertmodel, f)
            #     with open(f"train{e}_history{batch_id}.history", 'wb') as f:
            #         pickle.dump(train_history, f)
            #     with open(f"loss{e}_history{batch_id}.history", 'wb') as f:
            #         pickle.dump(loss_history, f)

            train_state['loss'].append(loss.data.cpu().numpy())
            train_state['acc'].append(train_acc / (batch_id+1))
            train_state = update_train_state(model=bertmodel,
                                            train_state=train_state)

            if train_state['stop_early']:
                break


            # train_acc += calc_accuracy(out.logits, label)
            # # train_acc += loss.item()
                        
            # if batch_id % log_interval == 0:
            #     print("epoch {} batch id {} loss {} train acc {}".format(e+1, batch_id+1, loss.data.cpu().numpy(), train_acc / (batch_id+1)))          #############################################################################
            #     train_history.append(train_acc / (batch_id+1))
            #     loss_history.append(loss.data.cpu().numpy()) #######################################################################################
                
        # print("epoch {} train acc {}".format(e+1, train_acc / (batch_id+1)))
    





        # EVALUATING
        bertmodel.eval()
        for batch_id, item in enumerate(tqdm(test_loader)):
       
            if batch_id % log_interval == 0 : 
                print(f"Epoch : {e+1} in {epochs} / Minibatch Step : {batch_id}")
                        
            input_ids, attention_mask, token_type_ids, label = item
            label = label.squeeze(1)
        
            out = bertmodel(input_ids, attention_mask, token_type_ids)
            
            test_acc += calc_accuracy(out.logits, label)

        print("epoch {} test acc {}".format(e+1, test_acc / (batch_id+1)))
        test_history.append(test_acc / (batch_id+1))
    
    # trained model saving...
    # print('trained model saving...')
    # fileNameForTrainedModel = f'kobertbasev1model_trained_{datetime.now()}.pickle' 
    # with open(fileNameForTrainedModel, 'wb') as f:
    #     pickle.dump(bertmodel, f, pickle.HIGHEST_PROTOCOL)
    # print()

    #질문 무한반복하기! 0 입력시 종료
    while True :
        sentence = input("분류를 위한 사건 텍스트를 입력한 후 엔터키를 누르십시오: ")
        if sentence == "0" :
            break
        predict(sentence)
        print("\n")







