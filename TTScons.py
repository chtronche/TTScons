import os, os.path, re, time

from SCons.Environment import Environment

def _readConfFile():
    confFile = file(os.path.join(os.environ['HOME'], '.ttscons'))
    if not confFile: return {}
    # Ultra-crude parser !
    return dict((line.rstrip().split('=', 1)  for line in confFile if not line.startswith('#')))

_conf = _readConfFile()

_arduinoDir = os.environ.get('ARDUINO_DIR') or _conf.get('ARDUINO_DIR')
if not _arduinoDir:
    raise Exception('Please set ARDUINO_DIR with your arduino environment path, either as an environment variable or in your $HOME/.ttscons file')

def _parseBoardsTxt(variant='teensy31'):
    variantDotLen = len(variant) + 1
    return dict((_.rstrip()[variantDotLen:].split('=', 1)
            for _ in file(os.path.join(_arduinoDir, 'hardware/teensy/avr/boards.txt'))
            if _.startswith(variant)))

_extractRe = re.compile(r'{([^}]*)}')
_purifyRe = re.compile(r' (-o|-c|"{source_file}"|"{object_file}"|{object_files})( |$)')

_linkNotMapped = frozenset('"{build.path}/{archive_file}" "-L{build.path}" {build.flags.libs} {object_files}'.split())

class _PlatformTxtParser:

    def __init__(self, boardsTxt, options, target):
        self.d = d = boardsTxt.copy()
        d['runtime.ide.path'] = _arduinoDir
        d['includes'] = '' # Not using the rules here, scons will take care of it
        d['build.path'] = '.' # Still in dev
        d['archive_file'] = 'XXX'
        d['extra.time.local'] = '%d' % time.time()
        d['build.core.path'] = os.path.join(_arduinoDir, 'hardware/teensy/avr/cores/teensy3')
        d['build.project_name'] = target
        d['build.elfpatch'] = 'BUILD.ELFPATCH'
        d['sketch_path'] = 'SKETCH_PATH'
        d['cmd.path'] = 'CMD.PATH'
        
        # highly inefficient (o^2), but hell
        for k, v in options.iteritems():
            selector = 'menu.%s.%s.' % (k, v)
            selectorLen = len(selector)
            for key in boardsTxt:
                if not key.startswith(selector): continue
                d[key[selectorLen:]] = boardsTxt[key]

    #
    # The following methods take a line from platform.txt
    # _post_<rulename> is called after rulename is parsed
    # parse(self, rule) is the default method, basically, it performs
    # the variable substitution inside the rule
    # _parse_<rulename> can be used to override the default method.


    def parse(self, rule, purify=True):
        if purify:
            while True:
                 # remove what is handled through scons construction variables
                newRule = _purifyRe.sub(' ', rule)
                if newRule == rule: break
                rule = newRule
        
        while True:
            m = _extractRe.search(rule)
            if not m: return rule
            rule = '%s%s%s' % (
                rule[:m.start(0)],
                self.d[rule[m.start(1):m.end(1)]],
                rule[m.end(0):])

    def _post_version(self):
        self.d['runtime.ide.version'] = self.d['version'].replace('.', '0') # Don't ask

    def _parse_recipe_c_combine_pattern(self, line):
        return self.parse(' '.join((_ for _ in line.split() if not _ in _linkNotMapped)), False)

def _parsePlatformTxt(boardsTxt, options, target):
    parser = _PlatformTxtParser(boardsTxt, options, target)
    for line in file(os.path.join(_arduinoDir, 'hardware/teensy/avr/platform.txt')):
        line = line.split('#')[0].rstrip()
        if not line: continue
        k, line = line.split('=', 1)
        kk = k.replace('.', '_')
        v = getattr(parser, '_parse_' + kk, parser.parse)(line)
        parser.d[k] = v
        specialFn = getattr(parser, '_post_' + kk, None)
        if specialFn: specialFn()
    return parser.d

def _setEnv(env, boardsTxt, platformTxt):
    env['CPPPATH'] = platformTxt['build.core.path']
    # This is the tricky part, since there's no real correspondance
    # between platform.txt (using one line per command) and SCons
    # (which split the arguments make-style between various
    # variables). So I kind of "extract" informations for the
    # platform.txt file, hoping they won't change much from one
    # version to the next.
    # A much more simpler idea would be to hardcode everything in
    # YATScons from an "intelligent" (human) analysis of platform.txt, but it
    # would then need to be updated for every Arduino / Teensyduino
    # version, precisely what I think is the problem with sconsduino
    # that we're trying to solve.
    env['CXX'] = platformTxt['recipe.cpp.o.pattern']
    env['CC'] = platformTxt['recipe.c.o.pattern']
    env['AR'] = platformTxt['recipe.ar.pattern'].split(' ')[0]
    env['ASFLAGS'] = platformTxt['build.flags.S']
    print 'LINKCOM=', env['LINKCOM']
    env['LINKCOM'] = platformTxt['recipe.c.combine.pattern']
    print '30>>', env['LINKCOM']
    #env['SOURCES'] = 

_defaultOptions = {
    'speed': '72',
    'usb': 'serial',
    'keys': 'en-us',
}

def teensy31(target, userOptions={}, env=Environment()):
    options = _defaultOptions.copy()
    options.update(userOptions)
    boardsTxt = _parseBoardsTxt()
    platformTxt = _parsePlatformTxt(boardsTxt, options, target)
    _setEnv(env, boardsTxt, platformTxt)
    # ok
    # env.VariantDir('build', 'src')
    # env.Program('build/y', ['build/x.cpp', 'build/z.cpp'])
    #
    # ok
    # env.VariantDir('build', 'src')
    # env.Library('build/y', ['build/x.cpp', 'build/z.cpp'])
    #
    # ok
    #env.VariantDir('build/a', '/tmp/t/7/src')
    #env.Library('build/a/y', ['build/a/x.cpp', 'build/a/z.cpp'])

    env.VariantDir('build/lib', env['CPPPATH'])
    coreList = [os.path.join('build/lib', os.path.basename(_))
                for _ in env.Glob(os.path.join(env['CPPPATH'], '*.*'), strings=True)
                if not _.endswith('h')]
    env.Library('build/lib/core', coreList)
    env.VariantDir('build/code', '.')
    env.Program('build/code/' + target +'.elf', ['build/lib/libcore.a'])
