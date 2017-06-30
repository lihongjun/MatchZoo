# -*- coding: utf8 -*-
import os
import sys
import json
import argparse

from collections import OrderedDict

import keras
import keras.backend as K
from keras.models import Sequential, Model

from utils import *
from inputs import *
from metrics import *
from losses import *

def train(config):
    # read basic config
    global_conf = config["global"]
    optimizer = global_conf['optimizer']
    weights_file = global_conf['weights_file']
    num_batch = global_conf['num_batch']

    model = Model.from_config(config['model'])
    rank_eval = rank_evaluations.rank_eval(rel_threshold = 0.)

    loss = []
    for lobj in config['losses']:
      loss.append(rank_losses.get(lobj))
    metrics = []
    for mobj in config['metrics']:
        metrics.append(mobj)
    model.compile(optimizer=optimizer, loss=loss)
    print '[Model] Model Compile Done.'

    history = LossHistory()

    # read input config
    input_conf = config['inputs']
    share_input_conf = input_conf['share']

    # list all input tags and construct tags config
    input_train_conf = OrderedDict()
    input_eval_conf = OrderedDict()
    for tag in input_conf.keys():
        if 'phase' not in input_conf[tag]:
            continue
        if input_conf[tag]['phase'] == 'TRAIN':
            input_train_conf[tag] = {}
            input_train_conf[tag].update(share_input_conf)
            input_train_conf[tag].update(input_conf[tag])
        elif input_conf[tag]['phase'] == 'EVAL':
            input_eval_conf[tag] = {}
            input_eval_conf[tag].update(share_input_conf)
            input_eval_conf[tag].update(input_conf[tag])
    print '[Input] Process Input Tags. %s in TRAIN, %s in EVAL.' % (input_train_conf.keys(), input_eval_conf.keys())

    # collect dataset identification
    dataset = {}
    for tag in input_conf:
        if tag != 'share' and input_conf[tag]['phase'] == 'PREDICT':
            continue
        if 'text1_corpus' in input_conf[tag]:
            datapath = input_conf[tag]['text1_corpus']
            if datapath not in dataset:
                dataset[datapath], _ = read_data(datapath)
        if 'text2_corpus' in input_conf[tag]:
            datapath = input_conf[tag]['text2_corpus']
            if datapath not in dataset:
                dataset[datapath], _ = read_data(datapath)
    print '[Dataset] %s Dataset Load Done.' % len(dataset)

    # initial data generator
    train_gen = OrderedDict()
    train_genfun = OrderedDict()
    eval_gen = OrderedDict()
    eval_genfun = OrderedDict()

    for tag, conf in input_train_conf.items():
        print conf
        train_gen[tag] = PairGenerator( data1 = dataset[conf['text1_corpus']],
                                      data2 = dataset[conf['text2_corpus']],
                                      config = conf )
        train_genfun[tag] = train_gen[tag].get_batch_generator()

    for tag, conf in input_eval_conf.items():
        print conf
        eval_gen[tag] = ListGenerator( data1 = dataset[conf['text1_corpus']],
                                     data2 = dataset[conf['text2_corpus']],
                                     config = conf )  
        eval_genfun[tag] = eval_gen[tag].get_batch_generator()

    for i_e in range(global_conf['num_epochs']):
        print '[Train] @ %s epoch.' % i_e
        for tag, genfun in train_genfun.items():
            print '[Train] @ %s' % tag
            model.fit_generator(
                    genfun,
                    steps_per_epoch = num_batch,
                    epochs = 1,
                    verbose = 1
                ) #callbacks=[eval_map])
        res = dict([[k,0.] for k in metrics])
        
        for tag, genfun in eval_genfun.items():
            print '[Eval] @ %s' % tag
            num_valid = 0
            for input_data, y_true in genfun:
                y_pred = model.predict(input_data)
                curr_res = rank_eval.eval(y_true = y_true, y_pred = y_pred, metrics=metrics)
                for k, v in curr_res.items():
                    res[k] += v
                num_valid += 1
            print '[Eval] epoch: %d,' %( i_e ), '  '.join(['%s:%f'%(k,v/num_valid) for k, v in res.items()]), ' ...'
            sys.stdout.flush()
            eval_genfun[tag] = eval_gen[tag].get_batch_generator()

    model.save_weights(weights_file)

def predict(config):
    global_conf = config["global"]
    weights_file = global_conf['weights_file']

    model = Model.from_config(config['model'])
    model.load_weights(weights_file)
    rank_eval = rank_evaluations.rank_eval(rel_threshold = 0.)

    metrics = []
    for mobj in config['metrics']:
        metrics.append(mobj)
    res = dict([[k,0.] for k in metrics])

    ######## Read input config ########

    input_conf = config['inputs']
    share_input_conf = input_conf['share']

    # list all input tags and construct tags config
    input_predict_conf = OrderedDict()
    for tag in input_conf.keys():
        if 'phase' not in input_conf[tag]:
            continue
        if input_conf[tag]['phase'] == 'PREDICT':
            input_predict_conf[tag] = {}
            input_predict_conf[tag].update(share_input_conf)
            input_predict_conf[tag].update(input_conf[tag])
    print '[Input] Process Input Tags. %s in PREDICT.' % (input_predict_conf.keys())

    # collect dataset identification
    dataset = {}
    for tag in input_conf:
        if tag == 'share' or input_conf[tag]['phase'] == 'PREDICT':
            if 'text1_corpus' in input_conf[tag]:
                datapath = input_conf[tag]['text1_corpus']
                if datapath not in dataset:
                    dataset[datapath], _ = read_data(datapath)
            if 'text2_corpus' in input_conf[tag]:
                datapath = input_conf[tag]['text2_corpus']
                if datapath not in dataset:
                    dataset[datapath], _ = read_data(datapath)
    print '[Dataset] %s Dataset Load Done.' % len(dataset)

    # initial data generator
    predict_gen = OrderedDict()
    predict_genfun = OrderedDict()

    for tag, conf in input_predict_conf.items():
        print conf
        predict_gen[tag] = ListGenerator( data1 = dataset[conf['text1_corpus']],
                                     data2 = dataset[conf['text2_corpus']],
                                     config = conf )  
        predict_genfun[tag] = predict_gen[tag].get_batch_generator()

    ######## Read output config ########
    output_conf = config['outputs']

    for tag, genfun in predict_genfun.items():
        print '[Predict] @ %s' % tag
        num_valid = 0
        res_scores = {} 
        for input_data, y_true in genfun:
            y_pred = model.predict(input_data)
            curr_res = rank_eval.eval(y_true = y_true, y_pred = y_pred, metrics=metrics)
            for k, v in curr_res.items():
                res[k] += v

            y_pred = np.squeeze(y_pred)
            for p, y in zip(input_data['ID'], y_pred):
                if p[0] not in res_scores:
                    res_scores[p[0]] = {}
                res_scores[p[0]][p[1]] = y

            num_valid += 1

        if tag in output_conf:
            if output_conf[tag]['save_format'] == 'TREC':
                with open(output_conf[tag]['save_path'], 'w') as f:
                    for qid, dinfo in res_scores.items():
                        dinfo = sorted(dinfo.items(), key=lambda d:d[1], reverse=True)
                        for inum,(did, score) in enumerate(dinfo):
                            print >> f, '%s\tQ0\t%s\t%d\t%f\t%s'%(qid, did, inum, score, config['net_name'])
        print '[Predict] results: ', '  '.join(['%s:%f'%(k,v/num_valid) for k, v in res.items()])
        sys.stdout.flush()

def main(argv):
    parser = argparse.ArgumentParser()
    parser.add_argument('--phase', default='train', help='Phase: Can be train or predict, the default value is train.')
    parser.add_argument('--model_file', default='./models/matchzoo.model', help='Model_file: MatchZoo model file for the chosen model.')
    args = parser.parse_args()
    model_file =  args.model_file
    with open(model_file, 'r') as f:
        config = json.load(f)
    phase = args.phase
    if args.phase == 'train':
        train(config)
    elif args.phase == 'predict':
        predict(config)
    else:
        print 'Phase Error.'
    return

if __name__=='__main__':
    main(sys.argv)
