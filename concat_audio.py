import os, ctypes, random, traceback, argparse, datetime, string
import pyperclip, soundfile
# pip install pyperclip
# pip install soundfile
import win32com.client  # .lnk shortcuts
# pip install pywin32
import paths

""" 
    Concatenates randomly chosen sounds in one sound file.
    The resulting file is created in FL Studio's Packs/_gen folder.

    --paths One or more paths containing candidate sounds. Subfolders will be browsed too.
    --num Number of sounds to concatenate
    --len Length of every sound (0 to deactivate and use --gate)
    --gate When this dB threshold is reached, the sound is cut (ex: -20) (0 to deactivate and use --len)

"""
PATHS = ""
num_snds = 0
force_num_snds = False
longueur = 0
noise_gate = 0
fade_len = .3   # * .1 sec
pre_gen_browser_mode = False

#--------------------------------------------------------------------------------------
fade_len = fade_len *.1
fade_len = min(fade_len, longueur)
temp_prefix = '___temp'
max_msg_box = 10

#--------------------------------------------------------------------------------------
def get_args():
    global PATHS, num_snds, longueur, noise_gate, pre_gen_browser_mode, force_num_snds
    parser = argparse.ArgumentParser(description='Concatenante multiple audio files.')
    parser.add_argument('--paths', nargs='+', action="store", dest="PATHS", 
                        default=[paths.packs_path], help='Sound files will be included in result. Folder paths will have some (or all) of its contained files included in result. Multiple paths accepted.')
    parser.add_argument('--num', action="store", type=int, dest="num", default=10, help='number of sounds')
    parser.add_argument('--forceNum', action="store_true", dest="forceNum", help='If true, asking more sounds than provided will use some sounds more than once')
    parser.add_argument('--len', action="store", type=float, dest="len", default=0, help='lenght of each sample')
    parser.add_argument('--gate', action="store", dest="gate", default='0', help='threshold of noisegate')
    parser.add_argument('--preGenBrowser', action="store_true", dest="preGenBrowser", help='if the files were chosen in concat_audio browsing mode')
    arg_results = parser.parse_args()
    PATHS = arg_results.PATHS 
    num_snds = arg_results.num
    force_num_snds = arg_results.forceNum
    longueur = arg_results.len
    noise_gate = arg_results.gate
    pre_gen_browser_mode = arg_results.preGenBrowser

def get_input_paths():
    input_paths = PATHS
    for i_p in input_paths:
        assert os.path.isdir(i_p)
    return input_paths

def get_pre_gen_browser_snds(input_paths):
    folder_paths, file_paths = [], []
    i = 0
    found = False
    while i < len(input_paths):
        if (os.path.normpath(input_paths[i]) == paths.pre_gen_browser_dir):
            found = True
            break
        i += 1
    if found:
        input_paths.remove(paths.pre_gen_browser_dir)
        for path in os.listdir(paths.pre_gen_browser_dir):
            path = os.path.join(paths.pre_gen_browser_dir, path)
            if is_lnk(path):
                path = get_lnk_source(path)
            if os.path.isdir(path):
                folder_paths.append(path)
            elif is_sound_file(path):
                file_paths.append(path)
    return folder_paths, file_paths

def get_folder_sounds(folder_paths):
    sounds = []
    for p in folder_paths:
        sounds += get_folder_sounds_recursive(p)
    return sounds

def get_folder_sounds_recursive(root, snds=[]):
    for s in os.listdir(root):
        path = os.path.join(root, s)
        if is_lnk(path):
            path = get_lnk_source(path)     
        if os.path.isdir(path):
            get_folder_sounds_recursive(path, snds) 
        elif is_sound_file(path):
            snds.append(path)
    return snds

def is_sound_file(f):
    result = False
    if os.path.isfile(f):
        ext = os.path.splitext(f)[1].lower()
        sound_exts = ['.wav', '.wv', '.mp3', '.aif', '.aiff', '.ogg']
        if ext in sound_exts and not os.path.basename(f).startswith('._'):
            result = True
    return result

def choose_sounds(folder_snds, snd_files):
    # sound files must be in selection
    # folders sounds can be chosen or overlooked
    global num_snds, force_num_snds
    selection = []
    if (len(snd_files) >= num_snds):
        selection = snd_files
    else:
        selection = folder_snds + snd_files
        selection = selection[len(selection)-num_snds:]
    if (num_snds > len(selection)):
        if (force_num_snds):
            for _ in range(num_snds-len(selection)):
                selection.append(random.choice(selection))
        else:
            num_snds = len(selection)
    random.shuffle(selection)
    return selection


def gen_temp_files(snds):
    for i, s_path in enumerate(snds):
        if is_wav_vorbis(s_path):
            s_path = wav_to_ogg(s_path, i)
            snds[i] = s_path

        cmd = '{} -ss 00:00:00'.format(paths.ffmpeg_path)
        if (longueur != 0):
            cmd += ' -t {}'.format(longueur)
        sr = get_samplerate(s_path) 
        cmd += ' -i "{}" -ar {} '.format(s_path, sr)
        num_samples = int(longueur*sr) #python has a built-in module to get the sample rate of a wav file. The module pydub gives mp3 bit depth
        fade_start = int(num_samples - fade_len*sr)
        cmd += '-af '
        if longueur != 0:
            cmd += 'apad=whole_len={},afade=type=out:ss={}:d={}'.format(num_samples, fade_start, fade_len)
        elif noise_gate != 0:
            cmd += 'silenceremove=start_periods=0:start_duration=0:start_threshold=0:stop_periods=-1:stop_duration=0.01:stop_threshold={}dB'.format(noise_gate)
        output_path = os.path.join(paths.output_dir, '{}{:02d}.wav'.format(temp_prefix, i))
        cmd += ' -c:a pcm_s16le -ar 44100'      # force 44100 16 bits
        cmd += ' -ac 2'                         # force to stereo
        cmd += ' -y "{}"'.format(output_path)
        cmd += ' -hide_banner -loglevel error'
        os.system(cmd)

def is_wav_vorbis(s_path):
    result = False
    b = b''
    with open(s_path, 'rb') as f:
        b = f.read()
    if b'ENCODER=vorbis.acm' in b:
        result = True
    return result

def wav_to_ogg(s_path, i):
    b = b''
    with open(s_path, 'rb') as f:
        b = f.read()
    offset = b.index(b'OggS')
    b = b[offset:]
    ogg_path = os.path.join(paths.output_dir, '{}{:02d}.ogg'.format(temp_prefix, i))
    with open(ogg_path, 'wb') as f:
        f.write(b)
    return ogg_path

def get_samplerate(s_path):
    sr = 44100
    try:
        _, sr = soundfile.read(s_path)
    except:
        print("Can't retrieve sample rate of {}".format(s_path), "Arbitrarily say it's {}kHz".format(sr), sep="\n")
        pass
    return sr

def gen_output():
    os.chdir(paths.output_dir)
    temp_sounds = [s for s in os.listdir(paths.output_dir) if os.path.basename(s).startswith(temp_prefix) and os.path.basename(s).endswith('.wav')]
    if (len(temp_sounds) == 0):
        msg_box("No temp files found. Exiting.")
        return
    txt_path = os.path.join(paths.output_dir, "{}.txt".format(temp_prefix))
    txt = open(txt_path, 'w')
    for s in temp_sounds:
        txt.write("file '{}'\n".format(os.path.join(paths.output_dir, s)))
    txt.close()
    output_name = get_output_name()
    cmd = '{} -f concat -safe 0 -i "{}"'.format(paths.ffmpeg_path, txt_path)
    cmd += ' -c copy'                      # copy stream
    cmd += ' -y "{}.wav"'.format(os.path.join(paths.output_dir, output_name))
    cmd += ' -hide_banner -loglevel error'
    os.system(cmd)
    msg_box(output_name, copy=True)

# --------------------------------------
def get_output_name():
    global PATHS, num_snds, longueur, noise_gate
    folder_name = format_folder_name(PATHS)
    sound_cut_option = format_sound_cut_option(longueur, noise_gate)
    output_name = "_".join([folder_name, "n"+str(num_snds), sound_cut_option])
    temp_output_name = output_name
    nth_instance_of_name = 1
    for f in os.listdir(paths.output_dir):
        if f.lower().endswith('.wav'):
            name = os.path.basename(f)[:-4]
            if temp_output_name == name:
                nth_instance_of_name += 1
            if (nth_instance_of_name > 1):
                temp_output_name = "{}_{:02d}".format(output_name, nth_instance_of_name)
    output_name = temp_output_name
    return output_name

def format_folder_name(paths):
    global pre_gen_browser_mode
    if pre_gen_browser_mode:
        words = get_week_day() + "_" + get_random_letters(2) #str(time.time())
    else:
        words = ""
        for i in range(len(paths)):
            folder_name = os.path.basename(paths[i])
            if folder_name[0].isdigit() or folder_name[0] == "_":
                folder_name = folder_name[1:]
            folder_name = list(filter(lambda c: c != " ", folder_name))
            folder_name = list(map(lambda w: w[0].upper() + w[1:], folder_name))
            words += "".join(folder_name)
            if (i < len(paths)-1):
                words += "_"
    return words  

def format_sound_cut_option(longueur, noise_gate):
    word = ""
    if longueur:
        if longueur < 1:
            word = "short"
        elif longueur < 2:
            word = "mid"
        else:
            word = "long"
    elif noise_gate:
        word = "{}dB".format(noise_gate)
    return word

def get_week_day():
    day = datetime.datetime.today().weekday()
    return ["Lun", "Mar", "Merc", "Jeu", "Ven", "Sam", "Dim"][day]

def get_random_letters(n):
    txt = ""
    for i in range(n):
        txt += random.choice(string.ascii_letters)
    return txt

# --------------------------------------
def delete_temp_files():
    for f in os.listdir(paths.output_dir):
        if f.startswith(temp_prefix):
            f = os.path.join(paths.output_dir, f)
            os.remove(f)

def msg_box(*msg, copy=False, force=False):
    global max_msg_box
    if max_msg_box > 0 or force:
        output = ""
        for m in msg:
            output = output + str(m) + " "
        if copy:
            pyperclip.copy(output)
        ctypes.windll.user32.MessageBoxW(0, output, "", 1)
        print(output)
        max_msg_box = max_msg_box -1 
# --------------------------------------
def is_lnk(path):
    return path[-3:] == "lnk"

def get_lnk_source(path):
    shell = win32com.client.Dispatch("WScript.Shell")
    shortcut = shell.CreateShortCut(path)
    return shortcut.Targetpath


if __name__ == '__main__':
    try:
        delete_temp_files()
        get_args()
        input_paths = get_input_paths()
        if (pre_gen_browser_mode):
            snd_folders, required_snds = get_pre_gen_browser_snds(input_paths)
            input_paths += snd_folders
        folder_snds = get_folder_sounds(input_paths)
        chosen_snds = choose_sounds(folder_snds, required_snds)

        if (len(chosen_snds) > 0):
            gen_temp_files(chosen_snds)
            gen_output()
            delete_temp_files()
        else:
            raise Exception("No sounds chosen.")
    except:
        msg_box(traceback.format_exc(), force=True)