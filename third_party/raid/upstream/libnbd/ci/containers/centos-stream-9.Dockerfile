# THIS FILE WAS AUTO-GENERATED
#
#  $ lcitool manifest ci/manifest.yml
#
# https://gitlab.com/libvirt/libvirt-ci

FROM quay.io/centos/centos:stream9

RUN dnf --quiet distro-sync -y && \
    dnf --quiet install 'dnf-command(config-manager)' -y && \
    dnf --quiet config-manager --set-enabled -y crb && \
    dnf --quiet install -y epel-release && \
    dnf --quiet install -y epel-next-release && \
    dnf --quiet install -y \
                autoconf \
                automake \
                bash \
                bash-completion \
                ca-certificates \
                cargo \
                ccache \
                clang \
                diffutils \
                fuse3 \
                fuse3-devel \
                gawk \
                gcc \
                gcc-c++ \
                git \
                glib2-devel \
                glibc-devel \
                glibc-langpack-en \
                gnutls-devel \
                gnutls-utils \
                golang \
                iproute \
                jq \
                libev-devel \
                libtool \
                libxml2-devel \
                make \
                nbdkit \
                ocaml \
                ocaml-findlib \
                ocaml-ocamldoc \
                perl-Pod-Simple \
                perl-base \
                perl-podlators \
                pkgconfig \
                python3-devel \
                python3-flake8 \
                qemu-img \
                qemu-kvm \
                sed \
                tar \
                util-linux \
                valgrind && \
    dnf --quiet autoremove -y && \
    dnf --quiet clean all -y && \
    rpm -qa | sort > /packages.txt && \
    mkdir -p /usr/libexec/ccache-wrappers && \
    ln -s /usr/bin/ccache /usr/libexec/ccache-wrappers/c++ && \
    ln -s /usr/bin/ccache /usr/libexec/ccache-wrappers/cc && \
    ln -s /usr/bin/ccache /usr/libexec/ccache-wrappers/clang && \
    ln -s /usr/bin/ccache /usr/libexec/ccache-wrappers/g++ && \
    ln -s /usr/bin/ccache /usr/libexec/ccache-wrappers/gcc

ENV CCACHE_WRAPPERSDIR="/usr/libexec/ccache-wrappers"
ENV LANG="en_US.UTF-8"
ENV MAKE="/usr/bin/make"
