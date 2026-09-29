# Oracle for the differential tests: evaluates Gemfiles with Bundler's own DSL
# and prints what the DSL produced as JSON.
#
#   ruby scripts/oracle.rb OUT.json LIST.txt
#
# LIST.txt has one Gemfile path per line. OUT.json maps each path to either
# {"ok": true, ...} or {"ok": false, "error": "..."}.
#
# Oracle version: Ruby 2.6.10 with Bundler 1.17.2 (the system Ruby on macOS).
# `gemspec` is stubbed, as in the reader, which reports it without evaluating it.
# Evaluating a Gemfile runs its Ruby code. Only run this on files you trust.
require 'bundler'
require 'bundler/dsl'
require 'json'
require 'timeout'

Bundler.ui = Bundler::UI::Silent.new

class Bundler::Dsl
  def gemspec(opts = nil); end
end

# Records ENV reads made directly by the Gemfile (not by Bundler itself).
class EnvTracker
  def initialize(real, gemfile, log)
    @real = real
    @gemfile = gemfile
    @log = log
  end

  def method_missing(name, *args, &blk)
    loc = caller_locations(1, 1).first
    @log << "#{name}(#{args.map(&:to_s).join(',')})" if loc && loc.path == @gemfile
    @real.send(name, *args, &blk)
  end

  def respond_to_missing?(*)
    true
  end
end

def src_json(s)
  case s
  when nil then nil
  when Bundler::Source::Git
    o = s.options
    { type: 'git', uri: o['uri'], branch: o['branch'], tag: o['tag'], ref: o['ref'],
      submodules: o['submodules'], glob: o['glob'] }
  when Bundler::Source::Path
    { type: 'path', path: s.options['path'].to_s, glob: s.options['glob'] }
  when Bundler::Source::Rubygems
    { type: 'rubygems', remotes: s.remotes.map(&:to_s) }
  else
    { type: s.class.name }
  end
end

def dep_json(d)
  {
    name: d.name,
    requirement: d.requirement.to_s,
    requirements: d.requirement.requirements.map { |op, v| "#{op} #{v}" },
    groups: d.groups.map(&:to_s),
    platforms: d.platforms.map(&:to_s),
    source: src_json(d.source),
    autorequire: d.autorequire && d.autorequire.map { |x| x.is_a?(Symbol) ? x.to_s : x },
    type: d.type.to_s,
    env: d.instance_variable_get(:@env),
    install_if: !!d.instance_variable_get(:@should_include)
  }
end

def evaluate(path)
  ENV['BUNDLE_GEMFILE'] = path
  dsl = Bundler::Dsl.new
  log = []
  real_env = ENV
  Object.send(:remove_const, :ENV)
  Object.const_set(:ENV, EnvTracker.new(real_env, path, log))
  begin
    Timeout.timeout(20) { dsl.eval_gemfile(path, File.read(path)) }
  ensure
    Object.send(:remove_const, :ENV)
    Object.const_set(:ENV, real_env)
  end
  rv = dsl.instance_variable_get(:@ruby_version)
  {
    ok: true,
    sources: dsl.instance_variable_get(:@sources).rubygems_primary_remotes.reverse.map(&:to_s),
    ruby: rv && { versions: rv.versions, engine: rv.engine, engine_versions: rv.engine_versions,
                  patchlevel: rv.patchlevel },
    optional_groups: dsl.instance_variable_get(:@optional_groups).map(&:to_s),
    dependencies: dsl.dependencies.map { |d| dep_json(d) },
    env_access: log
  }
end

out_path, list_path = ARGV
res = {}
File.readlines(list_path).map(&:chomp).reject(&:empty?).each do |f|
  begin
    res[f] = evaluate(File.expand_path(f))
  rescue Exception => e # rubocop:disable Lint/RescueException
    res[f] = { ok: false, error: "#{e.class.name}: #{e.message.to_s.lines.map(&:strip).reject(&:empty?).join(' | ')[0, 300]}" }
  end
end
File.write(out_path, JSON.generate(res))
puts "files #{res.size} ok #{res.values.count { |v| v[:ok] }}"
